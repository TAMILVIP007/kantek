import inspect
import re
from typing import Callable

from utils.client import Client
from utils.config import Config
from utils.mdtex import *
from utils.pluginmgr import k, _Command, _Event

SECTION_PATTERN = re.compile(r'^(?P<name>[\w ]+:)$', re.MULTILINE)

MISC_TOPICS = ['parsers']


@k.command('help')
async def help_(client: Client, args, kwargs) -> MDTeXDocument:
    """Get help for Kantek commands.

    Arguments:
        `topic`: A help topic as listed by {prefix}help
        `subtopic`: Optional subtopic like subcommands

    Examples:
        {cmd} help
        {cmd} autobahn
        {cmd}
    """
    cmds = client.plugin_mgr.commands
    events = client.plugin_mgr.events
    config = Config()
    if not args:
        toc = MDTeXDocument()
        _cmds = []
        for name, cmd in cmds.items():
            if cmd.document:
                _cmds.append(', '.join(cmd.commands))
        toc.append(Section('Command List', *sorted(_cmds)))
        _events = [e.name for e in events if e.name]
        toc.append(Section('Event List', *sorted(_events)))
        toc.append(Section('Misc', 'parsers'))
        toc.append(Italic('Provide a command/event name as argument to get help for it.'))
        return toc
    topic, *subtopic = args
    if topic in MISC_TOPICS:
        return get_misc_topics(topic, subtopic)
    cmd = cmds.get(topic)
    if cmd is None:
        for _cmd in cmds.values():
            if topic in _cmd.commands:
                cmd = _cmd
                break
        for _event in events:
            if _event.name == topic:
                cmd = _event
                break
    if cmd is None:
        return MDTeXDocument(Section('Error', f'Unknown command or event {Code(topic)}'))
    if isinstance(cmd, _Command):
        return get_command_info(cmd, subtopic, config)
    elif isinstance(cmd, _Event):
        return get_event_info(cmd, subtopic, config)


def get_event_info(event, subcommands, config) -> MDTeXDocument:
    description = get_description(event.callback, '')
    return MDTeXDocument(Section(f'Help for {event.name}'), description)


def get_command_info(cmd, subcommands, config) -> MDTeXDocument:
    cmd_name = cmd.commands[0]
    if not subcommands:
        help_cmd = f'{config.cmd_prefix[0]}{cmd_name}'
        description = get_description(cmd.callback, help_cmd)
        help_msg = MDTeXDocument(Section(f'Help for {help_cmd}'), description)

        if cmd.admins:
            help_msg.append(Italic('This command can be used by group admins.'))

        if not cmd.private:
            help_msg.append(Italic('This command is public.'))

        if cmd.subcommands:
            subcommands = Section('Subcommands')
            for name, sc in cmd.subcommands.items():
                sc_description = inspect.getdoc(sc.callback)
                if sc_description:
                    sc_description = sc_description.split('\n')[0]
                else:
                    sc_description = Italic('No description provided.')
                subcommands.append(KeyValueItem(Italic(Bold(name)), sc_description,
                                                colon_styles=(Bold, Italic)))
            help_msg.append(subcommands)
    else:
        subcommand = cmd.subcommands.get(subcommands[0])

        if subcommand is None:
            return MDTeXDocument(
                Section('Error', f'Unknown subcommand {Code(subcommands[0])} for command {Code(cmd_name)}'))
        help_cmd = f'{config.cmd_prefix[0]}{cmd_name} {subcommand.command}'
        description = get_description(subcommand.callback, help_cmd)

        help_msg = MDTeXDocument(Section(f'Help for {help_cmd}'), description)

    return help_msg


def get_description(callback: Callable, help_cmd: str) -> str:
    config = Config()
    description = inspect.getdoc(callback)
    if description is None:
        return 'No description'
    description = description.format(cmd=help_cmd, prefix=config.cmd_prefix[0])
    description = SECTION_PATTERN.sub(str(Bold(r'\g<name>')), description)
    return description


def get_misc_topics(topic, subtopics) -> MDTeXDocument:
    config = Config()
    subtopic = subtopics[0] if subtopics else None
    if topic == 'parsers':
        if not subtopic:
            return MDTeXDocument(
                Section(
                    'Available Parsers',
                    KeyValueItem(
                        Italic(Bold('time')),
                        'Specify durations with a shorthand',
                        colon_styles=(Bold, Italic),
                    ),
                    KeyValueItem(
                        Italic(Bold('args')),
                        'Examples for the argument parser',
                        colon_styles=(Bold, Italic),
                    ),
                )
            )

        elif subtopic == 'time':
            return MDTeXDocument(
                Section('Time'),
                'Express a duration as a shorthand:\n'
                'Supports s, m, h, d and w for seconds, minutes, hours, days and weeks respectively.',
                Section('Examples:',
                        KeyValueItem(Code('1s'), '1 second'),
                        KeyValueItem(Code('20m'), '20 minutes'),
                        KeyValueItem(Code('3h'), '3 hours'),
                        KeyValueItem(Code('3h1d'), '3 hours and 1 day (27 hours)'),
                        KeyValueItem(Code('1w2d'), '1 week and 2 days (9 days)'),
                        KeyValueItem(Code('20m30s'), '20 minutes and 30 seconds'))
            )
        elif subtopic == 'args':
            return MDTeXDocument(
                Section('Arguments'),
                'Parse arguments into positional and keyword arguments. '
                'Convert values into their respective types',
                f'To test them out copy them and pass them to {Code(f"{config.cmd_prefix[0]}dev args")}',

                Section('Examples:',
                        SubSection('Positonal Arguments',
                                   Code('1 2 3'),
                                   Code('arg1 arg2 arg3')),
                        SubSection('Keyword Arguments',
                                   Code('kw: 1'),
                                   Code('keywordarg: True')),
                        SubSection('Flags',
                                   Code('-flag1 -flag2')),
                        SubSection('Quoted Strings',
                                   Code('kw: "string with spaces'),
                                   Code('"positional argument with spaces"')),
                        SubSection('Ranges',
                                   Code('range: 1..10'),
                                   Code('1..10'),
                                   Code('..10'),
                                   Code('ids: -10..20')),
                        SubSection('Lists',
                                   Code('vals: ["val1", "val2"]'),
                                   Code('vals: [1, 2, 3]'),
                                   Code('[1,2,3]')),
                        ),
            )
