import functools
from dataclasses import dataclass
import textwrap

from telethon.events import NewMessage
from telethon.tl.types import BotCommand, BotCommandScopeUsers
from telethon.tl.functions.bots import SetBotCommandsRequest

from proxy_globals import client


@dataclass
class CommandHelp:
  name: str
  docstring: str
  alias_for: 'CommandHelp' = None
  short_doc: str = ''

  def __post_init__(self):
    if self.docstring:
      self.docstring = textwrap.dedent(self.docstring).strip()
      self.short_doc = self.docstring.partition('\n')[0]
    if isinstance(self.alias_for, str):
      self.alias_for = HELP_TEXTS[self.alias_for]

  @classmethod
  def add(cls, *args, **kwargs):
    o = cls(*args, **kwargs)
    name = o.name
    if name in HELP_TEXTS:
      raise ValueError(f'{name} is already in the help list!')
    HELP_TEXTS[name] = o


HELP_TEXTS: dict[str, CommandHelp] = {}


def add_to_help(name, *aliases):
  def wrapper(handler):
    CommandHelp.add(name, handler.__doc__)
    for alias in aliases:
      CommandHelp.add(alias, None, name)
    @functools.wraps(handler)
    async def wrapped(event, *args, **kwargs):
      ret = await handler(
        event,
        show_help=make_show_help_func(name, event),
        *args, **kwargs
      )
      return ret
    return wrapped
  return wrapper


@client.on(NewMessage(pattern='/(help|start)$'))
@add_to_help('help')
async def global_help(event, show_help):
  """
  Shows help message for a command
  Usage: <code>/help [command]</code>
  """
  await event.respond(
    'To save some media, send <code>/add [optional tags]</code>'
    '\n\nYou can also reply to any media with keywords to save it. '
    '\nKeywords can start with ! or - to remove those tags, for example <code>-smile</code>.'
    '\n\nYou can recall media that you\'ve saved by using me inline.'
    '\n\nIf you need more info about a command send <code>/help [command]</code>',
    parse_mode='HTML'
  )


@client.on(NewMessage(pattern='(?i)/help ([a-z\d_]+)$'))
async def cmd_help(event):
  cmd = HELP_TEXTS.get(event.pattern_match[1], None)
  if not cmd:
    return await event.respond('I don\'t know what that command means!')
  out_lines = []
  while cmd.alias_for:
    out_lines.append(f'Alias for /{cmd.alias_for.name}')
    cmd = cmd.alias_for
  out_lines.append(cmd.docstring)
  await event.respond('\n'.join(out_lines), parse_mode='HTML')


def make_show_help_func(name, event):
  async def show_help(**kwargs):
    await event.respond(
      HELP_TEXTS[name].docstring,
      parse_mode='HTML',
      **kwargs
    )
  return show_help


async def on_done_loading():
  commands = []
  for cmd in HELP_TEXTS.values():
    description = cmd.short_doc
    if not description:
      description = f'Alias for /{cmd.alias_for.name}'
    commands.append(BotCommand(
      command=cmd.name,
      description=description
    ))

  await client(SetBotCommandsRequest(
    scope=BotCommandScopeUsers(),
    lang_code='',
    commands=commands
  ))
