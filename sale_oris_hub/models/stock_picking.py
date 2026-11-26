from odoo import _, fields, models
from odoo.exceptions import UserError


class StockPicking(models.Model):
    _inherit = "stock.picking"

    shipping_status = fields.Selection(
        [
            ("not_sent", "Not Sent"),
            ("waiting_pickup", "Carrier Coming for Pickup"),
            ("picked_up", "Picked Up"),
            ("in_transit", "In Transit"),
            ("delivered", "Delivered"),
            ("cancelled", "Cancelled"),
            ("exception", "Exception"),
        ],
        string="Shipping Status",
        default="not_sent",
        copy=False,
        tracking=True,
    )
    shipping_label = fields.Char("Shipping Label", copy=False, readonly=True)
    shipping_fee = fields.Integer("Shipping Fee", copy=False, readonly=True)
    shipping_insurance_fee = fields.Integer(
        "Shipping Insurance Fee", copy=False, readonly=True
    )
    shipping_response = fields.Text(
        "Shipping Response", copy=False, readonly=True
    )
    shipping_error = fields.Text("Shipping Error", copy=False, readonly=True)
    shipping_sent_at = fields.Datetime(
        "Shipping Sent At", copy=False, readonly=True
    )
    shipping_cancelled_at = fields.Datetime(
        "Shipping Cancelled At", copy=False, readonly=True
    )
    shipping_cancel_response = fields.Text(
        "Shipping Cancel Response", copy=False, readonly=True
    )
    def action_send_to_carrier(self):
        for picking in self:
            if picking.picking_type_code != "outgoing":
                raise UserError(_("Only delivery orders can be sent to a carrier."))
            if picking.state != "assigned":
                raise UserError(
                    _("Delivery %s must be Ready before sending it.")
                    % picking.name
                )
            if not picking.carrier_id:
                raise UserError(_("Select a delivery carrier first."))
            if picking.carrier_tracking_ref:
                raise UserError(
                    _("Delivery %s has already been sent to a carrier.")
                    % picking.name
                )
            picking.send_to_shipper()
        return True

    def action_cancel(self):
        for picking in self:
            if (
                picking.carrier_id
                and picking.carrier_tracking_ref
                and not picking.shipping_cancelled_at
            ):
                picking.carrier_id.cancel_shipment(picking)
        return super().action_cancel()
