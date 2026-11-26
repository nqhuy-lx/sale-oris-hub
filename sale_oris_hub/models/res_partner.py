from odoo import fields, models


class ResPartner(models.Model):
    _inherit = "res.partner"

    ward = fields.Char(
        string="Phường/Xã",
        help="Tên phường/xã theo địa chính Việt Nam 2 cấp.",
    )
