"""Module containing all operations related to PostgreSQL"""
import datetime
import json
from typing import Dict, Optional, List

import asyncpg as asyncpg
from asyncpg.pool import Pool

from database.types import BlacklistItem, Chat, BannedUser


class TableWrapper:
    def __init__(self, pool):
        self.pool: Pool = pool


class Chats(TableWrapper):

    async def add(self, chat_id: int) -> Optional[Chat]:
        """Add a Chat to the DB or return an existing one.
        Args:
            chat_id: The id of the chat
        Returns: The chat Document
        """
        async with self.pool.acquire() as conn:
            await conn.execute("INSERT INTO chats VALUES ($1, '{}') ON CONFLICT DO NOTHING", chat_id)
        return Chat(chat_id, {})

    async def get(self, chat_id: int) -> Chat:
        """Return a Chat document
        Args:
            chat_id: The id of the chat
        Returns: The chat Document
        """
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM chats WHERE id = $1", chat_id)
        if row:
            return Chat(row['id'], json.loads(row['tags']))
        else:
            return await self.add(chat_id)

    async def update_tags(self, chat_id: int, new: Dict):
        async with self.pool.acquire() as conn:
            await conn.execute("UPDATE chats SET tags=$1 WHERE id=$2", json.dumps(new), chat_id)


class AutobahnBlacklist(TableWrapper):
    async def add(self, item: str) -> Optional[BlacklistItem]:
        """Add a Chat to the DB or return an existing one.
        Args:
            item: The id of the chat
        Returns: The chat Document
        """
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(f"INSERT INTO blacklists.{self.name} (item) VALUES ($1) RETURNING id", str(item))
        return BlacklistItem(row['id'], item, False)

    async def get_by_value(self, item: str) -> Optional[BlacklistItem]:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(f"SELECT * FROM blacklists.{self.name} WHERE item = $1", str(item))
        if not row:
            return None
        if row['retired']:
            return None
        else:
            return BlacklistItem(row['id'], row['item'], row['retired'])

    async def get(self, index):
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(f"SELECT * FROM blacklists.{self.name} WHERE id = $1", index)
        return BlacklistItem(row['id'], row['item'], row['retired']) if row else None

    async def retire(self, item):
        async with self.pool.acquire() as conn:
            result = await conn.fetchrow(f"UPDATE blacklists.{self.name} SET retired=TRUE WHERE item=$1 RETURNING id", str(item))
        return result

    async def get_all(self) -> List[BlacklistItem]:
        """Get all strings in the Blacklist."""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(f"SELECT * FROM blacklists.{self.name} WHERE retired=false")
        return [BlacklistItem(row['id'], row['item'], row['retired']) for row in rows]

    async def get_indices(self, indices, _):
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(f"SELECT * FROM blacklists.{self.name} WHERE id = any($1::integer[])", indices)
        return [BlacklistItem(row['id'], row['item'], row['retired']) for row in rows]


class AutobahnBioBlacklist(AutobahnBlacklist):
    """Blacklist with strings in a bio."""
    hex_type = '0x0'
    name = 'bio'


class AutobahnStringBlacklist(AutobahnBlacklist):
    """Blacklist with strings in a message"""
    hex_type = '0x1'
    name = 'string'


class AutobahnChannelBlacklist(AutobahnBlacklist):
    """Blacklist with blacklisted channel ids"""
    hex_type = '0x3'
    name = 'channel'


class AutobahnDomainBlacklist(AutobahnBlacklist):
    """Blacklist with blacklisted domains"""
    hex_type = '0x4'
    name = 'domain'


class AutobahnFileBlacklist(AutobahnBlacklist):
    """Blacklist with blacklisted file sha 512 hashes"""
    hex_type = '0x5'
    name = 'file'


class AutobahnMHashBlacklist(AutobahnBlacklist):
    """Blacklist with blacklisted photo hashes"""
    hex_type = '0x6'
    name = 'mhash'


class BanList(TableWrapper):
    async def add_user(self, _id: int, reason: str) -> Optional[BannedUser]:
        # unused
        pass

    async def get_user(self, uid: int) -> Optional[BannedUser]:
        """Fetch a users document
        Args:
            uid: User ID
        Returns: None or the Document
        """
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM banlist WHERE id = $1", uid)
        if row:
            return BannedUser(row['id'], row['reason'])

    async def remove(self, uid, _):
        async with self.pool.acquire() as conn:
            await conn.execute("DELETE FROM banlist WHERE id = $1", uid)

    async def get_multiple(self, uids, _) -> List[BannedUser]:
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                'SELECT * FROM banlist WHERE id = ANY($1::BIGINT[])', uids
            )

        return [BannedUser(row['id'], row['reason']) for row in rows]

    async def count_reason(self, reason, _) -> int:
        async with self.pool.acquire() as conn:
            return (await conn.fetchrow("SELECT count(*) FROM banlist WHERE reason = $1", reason))['count']

    async def total_count(self, _) -> int:
        async with self.pool.acquire() as conn:
            return (await conn.fetchrow("SELECT count(*) FROM banlist"))['count']

    async def upsert_multiple(self, bans, _) -> None:
        bans = [(int(u['id']), str(u['reason']), datetime.datetime.now(), None) for u in bans]
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute('CREATE TEMPORARY TABLE _data(id BIGINT, reason TEXT, date TIMESTAMP, message TEXT)'
                                   ' ON COMMIT DROP;')
                await conn.copy_records_to_table('_data', records=bans)
                await conn.execute('''
                        INSERT INTO banlist
                        SELECT * FROM _data
                        ON CONFLICT (id)
                        DO UPDATE SET reason=excluded.reason, date=excluded.date
                    ''')

    async def get_all(self, _) -> List[BannedUser]:
        async with self.pool.acquire() as conn:
            rows = await conn.fetch('SELECT * FROM banlist')
        return [BannedUser(row['id'], row['reason']) for row in rows]

    async def get_all_not_in(self, not_in, _) -> List[BannedUser]:
        not_in = list(map(int, not_in))
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                'SELECT * FROM banlist WHERE NOT (id = ANY($1::BIGINT[]))', not_in
            )

        return [BannedUser(row['id'], row['reason']) for row in rows]


class Strafanzeigen(TableWrapper):
    async def add(self, data, key):
        async with self.pool.acquire() as conn:
            await conn.execute('INSERT INTO strafanzeigen VALUES ($1, $2)', key, data)
        return key

    async def get(self, key) -> Optional[str]:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow('SELECT data FROM strafanzeigen WHERE key = $1', key)
        return row['data'] if row else None


class Postgres:  # pylint: disable = R0902
    async def connect(self, host, port, username, password, name) -> None:
        if port is None:
            port = 5432
        self.pool = await asyncpg.create_pool(user=username, password=password,
                                              database=name, host=host, port=port)
        self.chats: Chats = Chats(self.pool)
        self.ab_bio_blacklist: AutobahnBioBlacklist = AutobahnBioBlacklist(self.pool)
        self.ab_string_blacklist: AutobahnStringBlacklist = AutobahnStringBlacklist(self.pool)
        self.ab_channel_blacklist: AutobahnChannelBlacklist = AutobahnChannelBlacklist(self.pool)
        self.ab_domain_blacklist: AutobahnDomainBlacklist = AutobahnDomainBlacklist(self.pool)
        self.ab_file_blacklist: AutobahnFileBlacklist = AutobahnFileBlacklist(self.pool)
        self.ab_mhash_blacklist: AutobahnMHashBlacklist = AutobahnMHashBlacklist(self.pool)
        self.ab_collection_map = {
            '0x0': self.ab_bio_blacklist,
            '0x1': self.ab_string_blacklist,
            '0x3': self.ab_channel_blacklist,
            '0x4': self.ab_domain_blacklist,
            '0x5': self.ab_file_blacklist,
            '0x6': self.ab_mhash_blacklist,
        }
        self.banlist: BanList = BanList(self.pool)
        self.strafanzeigen: Strafanzeigen = Strafanzeigen(self.pool)
