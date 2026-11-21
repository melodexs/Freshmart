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
list_products = _impl.list_products
get_product = _impl.get_product
save_product = _impl.save_product
delete_product = _impl.delete_product
count_products = _impl.count_products
adjust_stock = _impl.adjust_stock
reserve_stock = _impl.reserve_stock
get_setting = _impl.get_setting
set_setting = _impl.set_setting
add_audit = _impl.add_audit
get_audit = _impl.get_audit
confirm_payment = _impl.confirm_payment
get_favourites = _impl.get_favourites
add_favourite = _impl.add_favourite
remove_favourite = _impl.remove_favourite
popularity = _impl.popularity
list_addresses = _impl.list_addresses
save_address = _impl.save_address
delete_address = _impl.delete_address
update_profile = _impl.update_profile
get_discount = _impl.get_discount
list_discounts = _impl.list_discounts
save_discount = _impl.save_discount
discount_usage = _impl.discount_usage
claim_discount = _impl.claim_discount
release_discount = _impl.release_discount
save_image = _impl.save_image
get_image = _impl.get_image
ping = _impl.ping
