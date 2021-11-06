import os
import mimetypes
from collections import defaultdict
import functools
import time

from telethon import events, tl

from proxy_globals import client
import constants
import p_cached
from data_model import MediaTypes, TaggedDocument
from query_parser import parse_tags, ALIAS_TO_FIELD
import db, utils


def extract_taggable_media(handler):
  @functools.wraps(handler)
  async def wrapper(event, *args, **kwargs):
    reply = await event.get_reply_message()
    m_type = MediaTypes.from_media(reply.file.media) if reply else None
    ret = await handler(event, reply=reply, m_type=m_type, *args, **kwargs)
    if isinstance(ret, str):
      await event.respond(ret)
    return ret
  return wrapper


def format_tagged_doc(doc: TaggedDocument):
  info = []
  for alias in ('t', 'e', 'fn', 'p', 'a'):
    key = ALIAS_TO_FIELD[alias].name
    value = getattr(doc, key)
    if value:
      info.append(f'{alias}:{value}')
  return (
    f'Info for {doc.id}:'
    f'\ninfo: {" ".join(info)}'
    f'\ntags: {utils.html_format_tags(doc.tags)}'
    + (f'\nemoji: {" ".join(doc.emoji)}' if doc.emoji else '')
  )


async def get_media_generated_attrs(file):
  ext = mimetypes.guess_extension(file.mime_type)
  if file.name:
    ext = os.path.splitext(file.name)[1] or ext

  attrs = {
    'ext': ext.strip('.'),
    'is_animated': (file.mime_type == 'application/x-tgsticker'),
  }

  pack = await p_cached.get_sticker_pack(file.sticker_set)
  if pack:
    attrs['pack_name'] = pack.title
    attrs['pack_link'] = pack.short_name
    attrs['emoji'] = pack.sticker_emojis[file.media.id]

  # don't include filename for stickers with a pack
  if file.name and not pack:
    attrs['filename'] = file.name

  if file.title:
    attrs['title'] = file.title
  if file.performer and file.title:
    attrs['title'] = f'{file.performer} - {file.title}'

  return attrs


@client.on(events.NewMessage())
@utils.whitelist
@extract_taggable_media
async def on_tag(event, reply, m_type):
  m = event.message
  if m.raw_text[:1] in {'/', '.'}:
    return
  if not reply or not reply.media:
    return
  if not m_type:
    return 'I don\'t know how to handle that media type yet!'
  file_id, access_hash = reply.file.media.id, reply.file.media.access_hash
  owner = event.sender_id

  q = parse_tags(m.raw_text)
  if not q.fields:
    return

  for tag in q.get('tags'):
    if len(tag) > constants.MAX_TAG_LENGTH:
      return f'Tags are limited to a length of {constants.MAX_TAG_LENGTH}!'

  doc = (
    await db.get_user_media(owner, file_id)
    or TaggedDocument(
      owner=owner, id=file_id, access_hash=access_hash, type=m_type
    )
  )

  gen_attrs = await get_media_generated_attrs(reply.file)
  # don't replace user emoji with ones from pack
  if doc.emoji:
    gen_attrs.pop('emoji', None)
  doc = doc.merge(**gen_attrs)
  doc.last_used = round(time.time())

  # calculate new tags and emoji
  doc.tags = (doc.tags | q.get('tags')) - q.get('tags', is_neg=True)
  if len(doc.tags) > constants.MAX_TAGS_PER_FILE:
    return f'Only {constants.MAX_TAGS_PER_FILE} tags are allowed per file!'

  doc.emoji = (doc.emoji | q.get('emoji')) - q.get('emoji', is_neg=True)
  if len(doc.emoji) > constants.MAX_EMOJI_PER_FILE:
    return f'Only {constants.MAX_EMOJI_PER_FILE} emoji are allowed per file!'

  try:
    await db.update_user_media(owner, file_id, doc.to_dict())
  except ValueError as e:
    return f'Error: {e}'

  await event.reply(
    format_tagged_doc(doc),
    parse_mode='HTML'
  )


@client.on(events.NewMessage(pattern=r'/tags$'))
@utils.whitelist
@extract_taggable_media
async def show_tags(event: events.NewMessage.Event, reply, m_type):
  if not m_type:
    await event.reply('Reply to media to use this command.')
    return

  file_id = reply.file.media.id
  doc = await db.get_user_media(event.sender_id, file_id)
  if not doc:
    await event.reply('No tags found.')
    return

  await event.reply(
    format_tagged_doc(doc),
    parse_mode='HTML'
  )


@client.on(events.NewMessage(pattern=r'/(delete|remove)$'))
@utils.whitelist
@extract_taggable_media
async def show_tags(event: events.NewMessage.Event, reply, m_type):
  if not m_type:
    await event.reply('Reply to media to use this command.')
    return

  file_id = reply.file.media.id
  deleted_res = await db.delete_user_media(event.sender_id, file_id)
  await event.reply('Media deleted.' if deleted_res else 'Media not found.')