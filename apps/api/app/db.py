"""Picks the data layer: Postgres if DATABASE_URL is set, else the JSON file.

Routes call these functions only, so swapping stores never touches them.
"""

from __future__ import annotations

from . import config

if config.USE_POSTGRES:
    from . import db_postgres as _impl
    from .db_postgres import *  # noqa: F401,F403
else:
    from . import db_file as _impl
    from .db_file import *  # noqa: F401,F403

init = _impl.init
get_user_by_email = _impl.get_user_by_email
save_user = _impl.save_user
create_user = _impl.create_user
get_orders_for_user = _impl.get_orders_for_user
add_order = _impl.add_order
get_store_sms = _impl.get_store_sms
add_store_sms = _impl.add_store_sms
get_order = _impl.get_order
get_all_orders = _impl.get_all_orders
update_order_status = _impl.update_order_status
