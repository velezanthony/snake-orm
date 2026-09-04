"""Seed data: scales + deterministic generator, kept apart from the logic.

`Scale` fixes the size (minimal/normal/large/massive) and `seed(session, scale)` fills the 29 tables.
Each framework writes its own thin seeder that only creates the schema and calls `seed`. Re-exported
so the import stays flat (`from shared.data import Scale, seed`).
"""

from shared.data.factory import DEMO_PASSWORD as DEMO_PASSWORD
from shared.data.factory import seed as seed
from shared.data.scales import Scale as Scale
from shared.data.scales import ScaleSpec as ScaleSpec
from shared.data.scales import demo_scale as demo_scale
from shared.data.scales import scale_by_name as scale_by_name
