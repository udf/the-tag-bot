import os
import mimetypes
import time

from telethon import events

from proxy_globals import client
from emoji_extractor import strip_emojis
from data_model import TaggedDocument
from query_parser import ParsedQuery, format_tagged_doc, parse_tags
import db, utils
import p_cached
from p_help import add_to_help
import p_media_mode


# TODO: make this a method of TaggedDocument
def calculate_new_tags(doc: TaggedDocument, q: ParsedQuery):
  doc.tags = (doc.tags | q.get('tags')) - q.get('tags', is_neg=True)
  doc.emoji = (doc.emoji | q.get('emoji')) - q.get('emoji', is_neg=True)


async def get_media_generated_attrs(file):
  ext = mimetypes.guess_extension(file.mime_type)
  if file.name:
    ext = os.path.splitext(file.name)[1] or ext

  attrs = {
    'ext': ext.strip('.'),
    'is_animated': (file.mime_type == 'application/x-tgsticker'),
  }

  if file.emoji:
    _, attrs['emoji'] = strip_emojis(file.emoji)
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


async def get_doc_from_file(owner, m_type, file):
  file_id, access_hash = file.media.id, file.media.access_hash
  doc = (
    await db.get_media(owner, file_id)
    or TaggedDocument(
      owner=owner, id=file_id, access_hash=access_hash, type=m_type
    )
  )

  gen_attrs = await get_media_generated_attrs(file)
  # don't replace user emoji with ones from pack
  if doc.emoji:
    gen_attrs.pop('emoji', None)
  doc = doc.merge(**gen_attrs)
  doc.last_used = round(time.time())

  return doc


@client.on(events.NewMessage())
@utils.whitelist
@utils.extract_taggable_media
async def on_tag(event, reply, m_type):
  m = event.message
  if m.raw_text[:1] in {'/', '.'}:
    return
  if not reply or not reply.media:
    return
  if not m_type:
    return 'I don\'t know how to handle that media type yet!'

  q = parse_tags(m.raw_text)
  if not q.fields:
    return

  doc = await get_doc_from_file(event.sender_id, m_type, reply.file)
  calculate_new_tags(doc, q)

  try:
    await db.update_media(doc)
  except ValueError as e:
    return f'Error: {e}'

  await event.reply(
    format_tagged_doc(doc),
    parse_mode='HTML'
  )


@client.on(events.NewMessage(pattern=r'/set(.+)?$'))
@utils.whitelist
@utils.extract_taggable_media
@add_to_help('set')
async def set_tags(event: events.NewMessage.Event, reply, m_type, show_help):
  """
  Sets (replaces) the tags for media
  Reply to media to use this command. Note that any existing tags will be lost!
  Usage: <code>/set [new tags]</code>
  """
  if not reply or not m_type or not event.pattern_match[1]:
    return await show_help()

  q = parse_tags(event.pattern_match[1])
  if not q.fields:
    return

  doc = await get_doc_from_file(event.sender_id, m_type, reply.file)

  new_tags, new_emoji = q.get('tags'), q.get('emoji')
  if new_tags:
    doc.tags = new_tags
  if new_emoji:
    doc.emoji = new_emoji

  try:
    await db.update_media(doc)
  except ValueError as e:
    return f'Error: {e}'

  await event.respond(
    format_tagged_doc(doc),
    parse_mode='HTML'
  )


@client.on(events.NewMessage(pattern=r'/tags$'))
@utils.whitelist
@utils.extract_taggable_media
@add_to_help('tags')
async def show_tags(event: events.NewMessage.Event, reply, m_type, show_help):
  """
  Shows the tags for media that you have saved
  Reply to media to use this command.
  """

  if not m_type:
    return await show_help()

  file_id = reply.file.media.id
  doc = await db.get_media(event.sender_id, file_id)
  if not doc:
    await event.respond('No tags found.')
    return

  await event.respond(
    format_tagged_doc(doc),
    parse_mode='HTML'
  )


@client.on(events.NewMessage(pattern=r'/(delete|remove)$'))
@utils.whitelist
@utils.extract_taggable_media
@add_to_help('delete', 'remove')
async def delete(event: events.NewMessage.Event, reply, m_type, show_help):
  """
  Deletes media that you have saved.
  Reply to media or use the button below to delete something
  """

  if not m_type:
    return await show_help(buttons=[[
      utils.inline_pm_button('Delete', 'delete:yes')
    ]])

  file_id = reply.file.media.id
  deleted = await db.delete_media(event.sender_id, file_id)
  await event.reply('Media deleted.' if deleted else 'Media not found.')


@p_media_mode.default_handler.register('on_media')
async def on_taggable_delete(event, m_type, is_delete):
  if not is_delete:
    return
  deleted = await db.delete_media(event.sender_id, event.file.media.id)
  await event.respond('Media deleted.' if deleted else 'Media not found.')
