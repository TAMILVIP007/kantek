"""Plugin to manage the autobahn"""
import asyncio
import logging
import re
from collections import Counter

import logzero
from telethon.errors import MessageIdInvalidError
from telethon.tl.custom import Message

from database.database import Database, ItemDoesNotExistError
from utils import helpers, constants
from utils.client import Client
from utils.mdtex import *
from utils.pluginmgr import k

tlog = logging.getLogger('kantek-channel-log')
logger: logging.Logger = logzero.logger

AUTOBAHN_TYPES = {
    'bio': '0x0',
    'string': '0x1',
    'filename': '0x2',
    'channel': '0x3',
    'domain': '0x4',
    'file': '0x5',
    'mhash': '0x6',
    'tld': '0x7',
}
# any higher and the message will exceed the 100 entity limit
MAX_QUERY_ITEMS = 45

INVITELINK_PATTERN = re.compile(r'(?:joinchat|join)(?:/|\?invite=)(.*|)')


@k.command('autobahn', 'ab')
async def autobahn() -> MDTeXDocument:
    """Manage Autobahn blacklists.

    Each message will be checked for blacklisted items and if a match is found the user is automatically gbanned.
    """
    return MDTeXDocument(
        Section('Types',
                *[KeyValueItem(Bold(name), Code(code)) for name, code in AUTOBAHN_TYPES.items()]))


@autobahn.subcommand()
async def add(client: Client, db: Database, msg: Message, args,
              event) -> MDTeXDocument:    # pylint: disable = R1702
    """Add a item to its blacklist.

    Blacklist names are _not_ the hexadecimal short hands

    Arguments:
        `type`: One of the possible autobahn types (See {prefix}ab)
        `item`: The item to be blacklisted. Not required for the file and mhash blacklists.

    Examples:
        {cmd} domain example.com
        {cmd} string "invest with bitcoin"
        {cmd} channel @durov
    """
    item_type = args[0]
    items = args[1:]
    added_items = []
    existing_items = []
    skipped_items = []
    hex_type = AUTOBAHN_TYPES.get(item_type)
    blacklist = await db.blacklists.get(hex_type)
    warn_message = ''

    for item in items:  # pylint: disable = R1702
        if hex_type is None or blacklist is None:
            continue
        if hex_type == '0x3':
            _item = item
            _, chat_id, _ = await helpers.resolve_invite_link(item)
            item = chat_id
            if item is None:
                if _item.startswith('tg://resolve'):
                    # tg://resolve?domain=<username>&start=<value>
                    params = re.split(r'[?&]', _item)[1:]
                    for param in params:
                        if param.startswith('domain'):
                            _, _item = param.split('=')
                else:
                    # remove any query parameters like ?start=
                    # replace @ aswell since some spammers started using it, only Telegram X supports it
                    _item = _item.split('?')[0].replace('@', '')
                try:
                    entity = await event.client.get_entity(_item)
                except constants.GET_ENTITY_ERRORS as err:
                    logger.error(err)
                    skipped_items.append(_item)
                    continue
                if entity:
                    item = entity.id
        elif hex_type == '0x4':
            item = (await client.resolve_url(item)).lower()
            if item in constants.TELEGRAM_DOMAINS:
                skipped_items.append(item)
                continue
        elif hex_type == '0x7':
            item = item.replace('.', '')
        # avoids "null" being added to the db
        if item is None:
            skipped_items.append(item)
            continue
        existing_one = await blacklist.get_by_value(item)
        if not existing_one:
            entry = await blacklist.add(item)
            added_items.append(KeyValueItem(entry.index, Code(entry.value)))
        else:
            existing_items.append(KeyValueItem(existing_one.index, Code(existing_one.value)))

    if not items and hex_type == '0x5':
        if not msg.is_reply:
            return MDTeXDocument(Section('Error', 'Need to reply to a file'))
        reply_msg: Message = await msg.get_reply_message()
        if not reply_msg.file:
            return MDTeXDocument(Section('Error', 'Need to reply to a file'))
        await msg.edit('Downloading file, this may take a while.')

        file = await reply_msg.download_media(
            bytes,
            progress_callback=lambda r, t: _sync_file_callback(r, t, msg))
        file_hash = helpers.hash_file(file)
        await msg.delete()
        existing_one = await blacklist.get(item)

        if not existing_one:
            entry = await blacklist.add(file_hash)
            short_hash = f'{entry.value[:15]}[...]'
            KeyValueItem(entry.index, Code(short_hash))
        else:
            existing_items.append(KeyValueItem(existing_one.index, Code(existing_one.value)))
    if not items and hex_type == '0x6':
        if not msg.is_reply:
            return MDTeXDocument(Section('Error', 'Need to reply to a photo'))

        reply_msg: Message = await msg.get_reply_message()
        if not reply_msg.photo:
            return MDTeXDocument(Section('Error', 'Need to reply to a photo'))
        await msg.edit('Hashing photo, this may take a moment.')

        dl_photo = await reply_msg.download_media(bytes)
        photo_hash = await helpers.hash_photo(dl_photo)
        await msg.delete()
        existing_one = await blacklist.get_by_value(photo_hash)

        if not existing_one:
            entry = await blacklist.add(photo_hash)
            if Counter(photo_hash).get('0', 0) > 8:
                warn_message = ('The image seems to contain a lot of the same color.'
                                ' This might lead to false positives.')

            added_items.append(KeyValueItem(entry.index, Code(entry.value)))
        else:
            existing_items.append(KeyValueItem(existing_one.index, Code(existing_one.value)))
    return MDTeXDocument(Section('Added Items:',
                                 SubSection(item_type,
                                            *added_items)) if added_items else '',
                         Section('Existing Items:',
                                 SubSection(item_type,
                                            *existing_items)) if existing_items else '',
                         Section('Skipped Items:',
                                 SubSection(item_type,
                                            *skipped_items)) if skipped_items else '',
                         Section('Warning:',
                                 warn_message) if warn_message else ''
                         )


@autobahn.subcommand()
async def del_(db: Database, args) -> MDTeXDocument:
    """Remove a item from its blacklist.

    Blacklist names are _not_ the hexadecimal short hands

    Arguments:
        `type`: One of the possible autobahn types (See {prefix}ab)
        `item`: The item to be blacklisted. Not required for the file and mhash blacklists.

    Examples:
        {cmd} domain example.com
        {cmd} string "invest with bitcoin"
        {cmd} channel @durov
    """
    item_type = args[0]
    items = args[1:]
    removed_items = []
    skipped_items = []
    for item in items:
        hex_type = AUTOBAHN_TYPES.get(item_type)
        blacklist = await db.blacklists.get(hex_type)
        if hex_type is None or blacklist is None:
            continue

        if hex_type == '0x3':
            _, chat_id, _ = await helpers.resolve_invite_link(str(item))
            item = chat_id

        try:
            await blacklist.retire(item)
            removed_items.append(Code(item))
        except ItemDoesNotExistError:
            skipped_items.append(Code(item))

    return MDTeXDocument(Section('Deleted Items:',
                                 SubSection(item_type, *removed_items)) if removed_items else None,
                         Section('Skipped Items:',
                                 SubSection(item_type, *skipped_items)) if skipped_items else None)


@autobahn.subcommand()
async def query(args, kwargs, db: Database) -> MDTeXDocument:
    """Query a blacklist for a specific code.

    Blacklist names are _not_ the hexadecimal short hands

    Arguments:
        `type`: One of the possible autobahn types (See {prefix}ab)
        `code`: The index of the item, can be a range

    Examples:
        {cmd} domain 3
        {cmd} channel 4..20
        {cmd} channel
    """
    item_type = kwargs.get('type')
    code = kwargs.get('code')
    if item_type is None and args:
        item_type = args[0]
    else:
        return MDTeXDocument(Section('Error', Italic('No blacklist name specified')))
    if code is None and len(args) > 1:
        code = args[1]

    hex_type = None
    blacklist = None
    if item_type is not None:
        hex_type = AUTOBAHN_TYPES.get(item_type, item_type)
        blacklist = await db.blacklists.get(hex_type)

    blacklist_items = await blacklist.get_all()

    if code is not None:
        if isinstance(code, int):
            code = [code]
        all_items = await blacklist.get_indices(list(code)[:MAX_QUERY_ITEMS])
    else:
        all_items = blacklist_items
    items = [KeyValueItem(Bold(item.index), Code(item.value)) for item in all_items[:MAX_QUERY_ITEMS]]

    return MDTeXDocument(
        Section(f'Items for type: {item_type}[{hex_type}]', *items or [Italic('None')]),
        Italic(f'Total count: {len(blacklist_items)}') if blacklist_items else None
    )

    # if hex_type is not None and code is not None:
    #     if isinstance(code, int):
    #         items = [code]
    #     items = blacklist.get_indices(list(code))
    #     items = [KeyValueItem(Bold(f'0x{item.index}'.rjust(5)),
    #                           Code(item.value)) for item in items]
    #     return MDTeXDocument(Section(f'Items for for type: {item_type}[{hex_type}]'), *items)


@autobahn.subcommand()
async def count(db: Database) -> MDTeXDocument:
    """Display item count of each blacklist

    Examples:
        {cmd}
    """
    sec = Section('Blacklist Item Count')
    for hextype, blacklist in db.blacklists._map.items():
        name = f'{blacklist.__class__.__name__.replace("Blacklist", "")} [{Code(hextype)}]'
        sec.append(KeyValueItem(name, len(await blacklist.get_all())))

    return MDTeXDocument(sec)


def _sync_file_callback(received: int, total: int, msg: Message) -> None:
    loop = asyncio.get_event_loop()
    loop.create_task(_file_callback(received, total, msg))
    # msg.edit(args)


async def _file_callback(received: int, total: int, msg: Message) -> None:
    text = MDTeXDocument(
        Section('Downloading File',
                KeyValueItem('Progress',
                             f'{received / 1024 ** 2:.2f}/{total / 1024 ** 2:.2f}MB'
                             f' ({(received / total) * 100:.0f}%)')))
    try:
        await msg.edit(str(text))
    except MessageIdInvalidError as err:
        logger.error(err)
