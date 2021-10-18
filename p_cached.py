import functools
from dataclasses import dataclass
from collections import defaultdict

from telethon import errors
from telethon.tl.types.messages import StickerSet
from telethon.tl.functions.messages import GetStickerSetRequest
from cachetools import keys, LRUCache

from proxy_globals import client


# Abridged version of https://github.com/hephex/asyncache
def acached(cache, key=keys.hashkey):
  def decorator(func):
    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
      k = key(*args, **kwargs)
      try:
        return cache[k]
      except KeyError:
        pass  # key not found
      val = await func(*args, **kwargs)
      try:
        cache[k] = val
      except ValueError:
        pass  # val too large
      return val
    return wrapper
  return decorator


# StickerSet without unused data
@dataclass
class CachedStickerSet:
  sticker_emojis: defaultdict[int, list[str]]
  title: str
  short_name: str

  def __init__(self, sticker_set: StickerSet):
    self.sticker_emojis = defaultdict(list)
    for pack in sticker_set.packs:
      for doc_id in pack.documents:
        self.sticker_emojis[doc_id].append(pack.emoticon)

    self.title = sticker_set.set.title
    self.short_name = sticker_set.set.short_name


@acached(LRUCache(1024), key=lambda ss: getattr(ss, 'id', 0))
async def get_sticker_pack(sticker_set):
  if not sticker_set:
    return
  try:
    return CachedStickerSet(await client(GetStickerSetRequest(sticker_set)))
  except errors.StickersetInvalidError:
    return
