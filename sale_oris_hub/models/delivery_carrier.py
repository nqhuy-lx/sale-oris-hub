import json

from odoo import _, api, fields, models
from odoo.exceptions import UserError


class DeliveryCarrier(models.Model):
    _inherit = "delivery.carrier"

    delivery_type = fields.Selection(
        selection_add=[("ghtk", "GHTK")],
        ondelete={"ghtk": "set default"},
    )
    ghtk_pickup_partner_id = fields.Many2one(
        "res.partner",
        string="GHTK Pickup Partner",
        check_company=True,
    )
    ghtk_fee_request_code = fields.Char(
        "GHTK Fee Request Code",
        default="ORIS_GET_GHTK_FEE",
    )
    ghtk_create_request_code = fields.Char(
        "GHTK Create Request Code",
        default="ORIS_CREATE_GHTK_ORDER",
    )
    ghtk_cancel_request_code = fields.Char(
        "GHTK Cancel Request Code",
        default="ORIS_CANCEL_GHTK_ORDER",
    )
    ghtk_tracking_url = fields.Char(
        "GHTK Tracking URL",
        default="https://i.ghtk.vn/<shipmenttrackingnumber>",
    )

    def _get_partner_address(self, partner):
        if not partner:
            raise UserError(_("A partner address is required."))
        if not partner.country_id or partner.country_id.code != "VN":
            raise UserError(
                _("%s must have Country set to Vietnam.") % partner.display_name
            )
        if not partner.state_id:
            raise UserError(_("%s is missing Province/City.") % partner.display_name)
        if not partner.ward:
            raise UserError(_("%s is missing Ward/Commune.") % partner.display_name)
        phone = partner.phone or partner.mobile
        if not phone:
            raise UserError(_("%s is missing a phone number.") % partner.display_name)
        address = " ".join(
            value for value in (partner.street, partner.street2) if value
        ).strip()
        if not address:
            raise UserError(_("%s is missing the address.") % partner.display_name)
        return {
            "name": partner.name,
            "address": address,
            "province": partner.state_id.name,
            "ward": partner.ward,
            "street": partner.street or False,
            "hamlet": partner.street2 or "Khác",
            "tel": phone,
        }

    def _get_pickup_address(self):
        self.ensure_one()
        if not self.ghtk_pickup_partner_id:
            raise UserError(_("Configure the GHTK pickup partner on the carrier."))
        partner = self.ghtk_pickup_partner_id
        address = self._get_partner_address(partner)
        return {
            "pick_name": address["name"],
            "pick_address": address["address"],
            "pick_province": address["province"],
            "pick_ward": address["ward"],
            "pick_tel": address["tel"],
            **({"pick_street": partner.street} if partner.street else {}),
        }

    def _get_picking_products(self, picking):
        products = []
        for move in picking.move_ids_without_package.filtered(
            lambda line: line.state != "cancel"
            and line.product_id
            and line.quantity > 0
        ):
            if move.product_id.weight <= 0:
                raise UserError(
                    _("Product %s must have a weight greater than zero.")
                    % move.product_id.display_name
                )
            quantity = move.quantity
            unit_price = 0
            sale_line = move.sale_line_id
            if sale_line:
                quantity = move.product_uom._compute_quantity(
                    move.quantity,
                    sale_line.product_uom,
                )
                unit_price = sale_line.price_unit * (
                    1 - (sale_line.discount or 0.0) / 100
                )
            products.append(
                {
                    "name": move.product_id.display_name,
                    "weight": move.product_id.weight,
                    "quantity": quantity,
                    "product_code": (
                        move.product_id.default_code or str(move.product_id.id)
                    ),
                    "price": unit_price,
                }
            )
        if not products:
            raise UserError(
                _(
                    "The delivery has no quantity ready to send. "
                    "Set the delivered quantity before sending it to GHTK."
                )
            )
        return products

    def _get_picking_weight_grams(self, picking):
        products = self._get_picking_products(picking)
        return int(
            round(
                sum(
                    product["weight"] * product["quantity"] * 1000
                    for product in products
                )
            )
        )

    def _get_ghtk_payload(self, picking):
        if not picking.sale_id:
            raise UserError(_("This delivery is not linked to a sale order."))
        pickup = self._get_pickup_address()
        delivery_partner = picking.partner_id or picking.sale_id.partner_shipping_id
        delivery = self._get_partner_address(delivery_partner)
        products = self._get_picking_products(picking)
        amount = sum(
            product["price"] * product["quantity"] for product in products
        )
        total_weight = sum(
            product["weight"] * product["quantity"] for product in products
        )
        delivery_payload = {
            key: delivery[key]
            for key in ("name", "address", "province", "ward", "hamlet", "tel")
        }
        if delivery["street"]:
            delivery_payload["street"] = delivery["street"]
        return {
            "products": products,
            "order": {
                "id": picking.name,
                **pickup,
                **delivery_payload,
                "pick_money": round(amount),
                "value": round(amount),
                "is_freeship": 1,
                "weight_option": "kilogram",
                "total_weight": total_weight,
                "pick_option": "cod",
            },
        }

    def _run_hub_request(self, code, environments, picking=None, company=None):
        company = company or (picking.company_id if picking else self.env.company)
        record_id = picking.id if picking else False
        request = self.env["hub.request"]._find_request_by_code(
            code,
            {"COMPANY_ID": company.id},
        )
        if not request:
            raise UserError(
                _("No ORIS HUB request was found with code %s.") % code
            )
        runtime = dict(environments)
        runtime.update(
            {
                "record_id": record_id,
                "__force_sync": True,
            }
        )
        result = request.run_request(runtime).get("RESULT_%s" % request.code)
        if isinstance(result, str):
            try:
                return json.loads(result)
            except json.JSONDecodeError as error:
                raise UserError(
                    _("ORIS HUB returned invalid JSON: %s") % error
                ) from error
        if not isinstance(result, dict):
            raise UserError(_("ORIS HUB returned an empty response."))
        return result

    def ghtk_rate_shipment(self, order):
        partner = order.partner_shipping_id or order.partner_id
        delivery = self._get_partner_address(partner)
        products = []
        for line in order.order_line.filtered(
            lambda line: not line.is_delivery
            and not line.display_type
            and line.product_id
        ):
            quantity = line.product_uom._compute_quantity(
                line.product_uom_qty,
                line.product_id.uom_id,
            )
            products.append(
                {
                    "weight": line.product_id.weight,
                    "quantity": quantity,
                }
            )
        weight_grams = int(
            round(
                sum(
                    product["weight"] * product["quantity"] * 1000
                    for product in products
                )
            )
        )
        pickup = self._get_pickup_address()
        if not weight_grams:
            return {
                "success": False,
                "price": 0.0,
                "error_message": _("The order has no weight."),
            }
        picking = self.env["stock.picking"]
        delivery_partner = partner
        result = self._run_hub_request(
            self.ghtk_fee_request_code,
            {
                "PARAMS": {
                    "province": delivery["province"],
                    "district": delivery["ward"],
                    "pick_province": pickup["pick_province"],
                    "pick_ward": pickup["pick_ward"],
                    "weight": weight_grams,
                },
            },
            company=order.company_id,
        )
        fee_data = result.get("fee") or {}
        if not result.get("success"):
            return {
                "success": False,
                "price": 0.0,
                "error_message": result.get("message") or _("GHTK fee lookup failed."),
            }
        if not fee_data.get("delivery"):
            return {
                "success": False,
                "price": 0.0,
                "error_message": _("GHTK does not support this address."),
            }
        return {
            "success": True,
            "price": float(fee_data.get("fee") or 0),
            "carrier_price": float(fee_data.get("fee") or 0),
        }

    def ghtk_rate_picking(self, picking):
        pickup = self._get_pickup_address()
        delivery = self._get_partner_address(
            picking.partner_id or picking.sale_id.partner_shipping_id
        )
        weight_grams = self._get_picking_weight_grams(picking)
        result = self._run_hub_request(
            self.ghtk_fee_request_code,
            {
                "PARAMS": {
                    "province": delivery["province"],
                    "district": delivery["ward"],
                    "pick_province": pickup["pick_province"],
                    "pick_ward": pickup["pick_ward"],
                    "weight": weight_grams,
                },
            },
            picking,
        )
        fee_data = result.get("fee") or {}
        return result, fee_data

    def ghtk_send_shipping(self, pickings):
        result = []
        for picking in pickings:
            payload = self._get_ghtk_payload(picking)
            response = self._run_hub_request(
                self.ghtk_create_request_code,
                {"BODY": payload},
                picking,
            )
            if not response.get("success"):
                raise UserError(
                    response.get("message") or _("GHTK rejected the order.")
                )
            ghtk_order = response.get("order") or {}
            tracking_number = str(ghtk_order.get("tracking_id") or "")
            if not tracking_number:
                tracking_number = ghtk_order.get("label") or ""
            if not tracking_number:
                raise UserError(_("GHTK response has no tracking number."))
            picking.write(
                {
                    "shipping_status": "waiting_pickup",
                    "shipping_fee": ghtk_order.get("fee") or 0,
                    "shipping_insurance_fee": (
                        ghtk_order.get("insurance_fee") or 0
                    ),
                    "shipping_label": ghtk_order.get("label") or "",
                    "shipping_response": json.dumps(
                        response, ensure_ascii=False
                    ),
                    "shipping_error": False,
                    "shipping_sent_at": fields.Datetime.now(),
                }
            )
            result.append(
                {
                    "exact_price": float(ghtk_order.get("fee") or 0),
                    "tracking_number": tracking_number,
                }
            )
        return result

    def ghtk_cancel_shipment(self, pickings):
        for picking in pickings:
            if not picking.carrier_tracking_ref:
                return True
            response = self._run_hub_request(
                self.ghtk_cancel_request_code,
                {
                    "TRACKING_ORDER": picking.carrier_tracking_ref,
                    "BODY": {},
                },
                picking,
            )
            if not response.get("success"):
                raise UserError(
                    response.get("message") or _("GHTK cancellation failed.")
                )
            picking.write(
                {
                    "shipping_status": "cancelled",
                    "shipping_cancelled_at": fields.Datetime.now(),
                    "shipping_cancel_response": json.dumps(
                        response, ensure_ascii=False
                    ),
                    "shipping_error": False,
                }
            )
        return True

    def ghtk_get_tracking_link(self, picking):
        if not picking.carrier_tracking_ref:
            return False
        return self.ghtk_tracking_url.replace(
            "<shipmenttrackingnumber>",
            picking.carrier_tracking_ref,
        )
