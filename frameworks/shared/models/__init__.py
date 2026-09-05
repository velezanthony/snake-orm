"""Shared SnakeORM models, split by DOMAIN (one file per domain).

Ten domains (accounts, auth, blog, content, engagement, taxonomy, billing, inventory, orders,
logistics) = 29 tables. Each one
declares its models; here they are ALL imported and `snake_link()` is called ONCE (it links the whole
graph in one go, cross-domain relationships included). The names are re-exported so that both
`from shared.models import User` and `from shared.models.accounts_models import User` work.

`MODELS` is in dependency order for the DDL: a parent always before any child that references it by
FK, even across different domains (accounts → blog → content → … → billing → … → logistics).
"""

from snakeorm.linker import snake_link

from shared.models.accounts_models import ACCOUNTS_MODELS as ACCOUNTS_MODELS
from shared.models.accounts_models import Role as Role
from shared.models.accounts_models import User as User
from shared.models.accounts_models import UserRole as UserRole
from shared.models.accounts_models import UserStats as UserStats
from shared.models.auth_models import AUTH_MODELS as AUTH_MODELS
from shared.models.auth_models import ApiToken as ApiToken
from shared.models.auth_models import LoginSession as LoginSession
from shared.models.billing_models import BILLING_MODELS as BILLING_MODELS
from shared.models.billing_models import Invoice as Invoice
from shared.models.billing_models import Payment as Payment
from shared.models.billing_models import CardPayment as CardPayment
from shared.models.billing_models import PaypalPayment as PaypalPayment
from shared.models.billing_models import TransferPayment as TransferPayment
from shared.models.billing_models import WalletPayment as WalletPayment
from shared.models.billing_models import Plan as Plan
from shared.models.billing_models import PlanStats as PlanStats
from shared.models.billing_models import Subscription as Subscription
from shared.models.blog_models import BLOG_MODELS as BLOG_MODELS
from shared.models.blog_models import Blog as Blog
from shared.models.blog_models import BlogStats as BlogStats
from shared.models.blog_models import Category as Category
from shared.models.blog_models import Post as Post
from shared.models.content_models import CONTENT_MODELS as CONTENT_MODELS
from shared.models.content_models import Attachment as Attachment
from shared.models.content_models import PostRevision as PostRevision
from shared.models.engagement_models import ENGAGEMENT_MODELS as ENGAGEMENT_MODELS
from shared.models.engagement_models import Comment as Comment
from shared.models.engagement_models import Reaction as Reaction
from shared.models.engagement_models import Visit as Visit
from shared.models.inventory_models import BOOK_SIZE as BOOK_SIZE
from shared.models.inventory_models import FLOOR_REASONS as FLOOR_REASONS
from shared.models.inventory_models import SHOP_REASONS as SHOP_REASONS
from shared.models.inventory_models import INVENTORY_MODELS as INVENTORY_MODELS
from shared.models.inventory_models import INVENTORY_VIEWS as INVENTORY_VIEWS
from shared.models.inventory_models import LowStock as LowStock
from shared.models.inventory_models import MovementReason as MovementReason
from shared.models.inventory_models import Sku as Sku
from shared.models.inventory_models import SkuKind as SkuKind
from shared.models.inventory_models import Stock as Stock
from shared.models.inventory_models import StockLedger as StockLedger
from shared.models.inventory_models import StockMovement as StockMovement
from shared.models.inventory_models import Timestamped as Timestamped
from shared.models.inventory_models import Warehouse as Warehouse
from shared.models.inventory_models import WarehouseStats as WarehouseStats
from shared.models.logistics_models import LOGISTICS_MODELS as LOGISTICS_MODELS
from shared.models.logistics_models import BAND_HOURS as BAND_HOURS
from shared.models.logistics_models import DISPATCH_LEAD_DAYS as DISPATCH_LEAD_DAYS
from shared.models.logistics_models import Delivery as Delivery
from shared.models.logistics_models import Depot as Depot
from shared.models.logistics_models import PackagingUnit as PackagingUnit
from shared.models.orders_models import ORDERS_MODELS as ORDERS_MODELS
from shared.models.orders_models import CustomerOrders as CustomerOrders
from shared.models.orders_models import Order as Order
from shared.models.orders_models import OrderLine as OrderLine
from shared.models.orders_models import OrderState as OrderState
from shared.models.taxonomy_models import TAXONOMY_MODELS as TAXONOMY_MODELS
from shared.models.taxonomy_models import PostTag as PostTag
from shared.models.taxonomy_models import Tag as Tag
from shared.models.taxonomy_models import TagGroup as TagGroup

# Every model, in dependency order for the DDL (parents before children, cross-domain references
# included): accounts → auth → blog → content → engagement → taxonomy → billing → inventory →
# orders → logistics. `orders` is the one domain whose position is FORCED: it references accounts,
# inventory AND billing, so it is the one place where the order of this tuple is not a
# convention but the difference between the DDL applying and the foreign keys failing.
#
# `logistics` sits after it and could sit anywhere, because it references nothing outside itself — a
# depot is not a warehouse and a delivery is not an order line. It goes last because it is newest,
# and saying so costs one line and saves the next reader working out whether the position means
# something.
MODELS = (
    ACCOUNTS_MODELS
    + AUTH_MODELS
    + BLOG_MODELS
    + CONTENT_MODELS
    + ENGAGEMENT_MODELS
    + TAXONOMY_MODELS
    + BILLING_MODELS
    + INVENTORY_MODELS
    + ORDERS_MODELS
    + LOGISTICS_MODELS
)

# The VIEWS, apart. They are not tables: they are created AFTER them (they read from them) and
# dropped BEFORE them, and `DROP TABLE` is not what removes one. Keeping them in `MODELS` would have
# every loop over it emit the wrong DDL for these two operations.
VIEWS = INVENTORY_VIEWS

# NOTHING IS INJECTED INTO ANYBODY'S GLOBALS HERE ANY MORE, and the absence is the point.
#
# The relationships CROSS domains and the domains live in different files, so `User` needs `Post`
# and `Post` needs `User`. Importing both ways at runtime is the cycle, which is why each module
# names the other under `if TYPE_CHECKING:`. But the linker resolves annotations with
# `get_type_hints()`, which evaluates against the module's RUNTIME globals — where a name imported
# only inside that block never is. So this file used to walk `sys.modules` and `setattr` the whole
# graph into every model module, and its own comment called that a seam that "needs this help
# today".
#
# It does not any more: `snakeorm.linker.hints_of` reads the `if TYPE_CHECKING:` block out of the
# source when `get_type_hints` cannot resolve a name, so each module resolves the names IT wrote,
# through the import path IT declared. That path is an identity; a class name is not (bug #14).
#
# Measured before deleting it: the whole graph links without the loop.

# Links the graph once, after importing every domain.
snake_link()
