MAX_TAG_LENGTH = 32
MAX_TAGS_PER_FILE = 10
MAX_EMOJI_PER_FILE = 48
MAX_MEDIA_PER_USER = 1000

# Telegram limitations
MAX_RESULTS_PER_PAGE = 50

# db
ELASTIC_USERNAME = 'tagbot'
class INDEX:
  main = 'tagbot'
  backup = 'tagbot_tmp'  # used for migrating when settings changes
  transfer = 'tagbot_transfer'