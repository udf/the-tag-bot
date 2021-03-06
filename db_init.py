import json
import logging
import hashlib

from elasticsearch import AsyncElasticsearch, NotFoundError

from secrets import HTTP_PASS, ADMIN_HTTP_PASS
from constants import ELASTIC_USERNAME, INDEX_NAME, INDEX_TRANSFER_NAME

BACKUP_INDEX_NAME = f'{INDEX_NAME}_tmp'
SETTINGS_HASH_FILE = 'settings.hash'
es_main = AsyncElasticsearch(http_auth=(ELASTIC_USERNAME, HTTP_PASS))
logger = logging.getLogger('db_init')

# Load settings and calculate hash of minified data
with open('settings.json') as f:
  settings = json.load(f)
settings_hash = hashlib.sha256(
  json.dumps(settings, ensure_ascii=True, sort_keys=True).encode('ascii')
).hexdigest()
logger.info(f'Current settings hash is {settings_hash}')

try:
  with open(SETTINGS_HASH_FILE) as f:
    old_settings_hash = f.read()
  logger.info(f'Previous settings hash is {old_settings_hash}')
except FileNotFoundError:
  logger.info('Previous settings hash not found')
  old_settings_hash = None


async def init_user():
  es_admin = AsyncElasticsearch(http_auth=('elastic', ADMIN_HTTP_PASS))
  logger.info('Updating user role...')
  await es_admin.security.put_role(
    name='tagbot',
    body={
      'cluster': ['monitor'],
      'indices': [
        {
          'names': [INDEX_NAME, BACKUP_INDEX_NAME, INDEX_TRANSFER_NAME],
          'privileges': ['all']
        }
      ]
    }
  )

  logger.info('Updating user...')
  await es_admin.security.put_user(
    username='tagbot',
    body={
      "password": HTTP_PASS,
      "roles": ["tagbot"],
      "full_name": "Tag Bot",
    }
  )


async def init_main_index():
  settings_are_stale = settings_hash != old_settings_hash
  main_index_exists = await es_main.indices.exists(index=INDEX_NAME)

  if await es_main.indices.exists(index=BACKUP_INDEX_NAME):
    logger.error('Backup index already exists!')
    raise RuntimeError(f'Backup index "{BACKUP_INDEX_NAME}" already exists, bailing out because it might contain data')

  if not main_index_exists:
    logger.info('Main index not found!')
    settings_are_stale = True
  if not settings_are_stale:
    return

  logger.info('The index will be (re-)initialized!')

  if main_index_exists:
    logger.info('Backing up main index...')
    # make index read only
    await es_main.indices.put_settings(
      index=INDEX_NAME,
      body={
        "settings": {
          "index.blocks.write": True
        }
      }
    )
    # copy to backup
    await es_main.indices.clone(index=INDEX_NAME, target=BACKUP_INDEX_NAME)
    # wait for clone to finish
    await es_main.cluster.health(index=BACKUP_INDEX_NAME, wait_for_status='yellow', timeout='30s')

    logger.info('Backup complete, deleting main index...')
    await es_main.indices.delete(index=INDEX_NAME)

  logger.info('Creating main index')
  await es_main.indices.create(
    index=INDEX_NAME,
    settings=settings['settings'],
    mappings=settings['mappings']
  )

  if main_index_exists:
    logger.info('Restoring backup...')
    await es_main.reindex(body={
      "source": {"index": BACKUP_INDEX_NAME},
      "dest": {"index": INDEX_NAME}
    })

    logger.info('Deleting backup...')
    await es_main.indices.delete(index=BACKUP_INDEX_NAME)

  logger.info('Writing new settings hash...')
  with open(SETTINGS_HASH_FILE, 'w') as f:
    f.write(settings_hash)


async def init_transfer_index():
  logger.info('Creating transfer index...')
  try:
    await es_main.indices.delete(index=INDEX_TRANSFER_NAME)
  except NotFoundError:
    logger.info('Previous transfer index not found!')
    pass

  await es_main.indices.create(
    index=INDEX_TRANSFER_NAME,
    settings=settings['settings'],
    mappings=settings['mappings']
  )


async def init():
  await init_user()
  await init_transfer_index()
  await init_main_index()
