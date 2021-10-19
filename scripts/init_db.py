import asyncio
from buildpg import asyncpg, funcs, RawDangerous

from .. import utils


async def init():
  pool = await asyncpg.create_pool_b(
    database='tagbot',
    user='tagbot',
    host='localhost'
  )

  await pool.fetch_b(
    'CREATE TYPE media_type AS ENUM (:values);',
    values=funcs.comma_sep(*(RawDangerous(f"'{v.value}'") for v in utils.MediaTypes))
  )

  # TODO: convert this into buildpg
  with open('db.sql') as f:
    sql = f.read()
  await pool.execute(sql)

  async with pool.acquire() as con:
    await con.execute(sql)


asyncio.run(init())