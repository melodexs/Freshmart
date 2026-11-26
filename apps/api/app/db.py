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
get_admin = _impl.get_admin
list_admins = _impl.list_admins
create_admin = _impl.create_admin
update_admin = _impl.update_admin
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
merge_payment_detail = _impl.merge_payment_detail
get_order_by_payment_reference = _impl.get_order_by_payment_reference
mark_paid_verified = _impl.mark_paid_verified
get_favourites = _impl.get_favourites
add_favourite = _impl.add_favourite
remove_favourite = _impl.remove_favourite
save_review = _impl.save_review
list_reviews = _impl.list_reviews
get_review = _impl.get_review
set_review_hidden = _impl.set_review_hidden
add_subscriber = _impl.add_subscriber
remove_subscriber = _impl.remove_subscriber
list_subscribers = _impl.list_subscribers
add_reset_token = _impl.add_reset_token
use_reset_token = _impl.use_reset_token
peek_reset_token = _impl.peek_reset_token
popularity = _impl.popularity
list_addresses = _impl.list_addresses
save_address = _impl.save_address
delete_address = _impl.delete_address
update_profile = _impl.update_profile
add_stock_move = _impl.add_stock_move
list_stock_moves = _impl.list_stock_moves
get_discount = _impl.get_discount
list_discounts = _impl.list_discounts
save_discount = _impl.save_discount
discount_usage = _impl.discount_usage
claim_discount = _impl.claim_discount
release_discount = _impl.release_discount
save_image = _impl.save_image
get_image = _impl.get_image
ping = _impl.ping
