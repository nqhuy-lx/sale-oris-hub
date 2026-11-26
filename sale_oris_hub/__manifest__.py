{
    "name": "Sale ORIS HUB",
    "version": "18.0.1.0.0",
    "category": "Sales",
    "summary": "Extensible delivery carriers through ORIS HUB",
    "depends": ["stock_delivery", "oris_hub"],
    "data": [
        "views/res_partner_views.xml",
        "views/delivery_carrier_views.xml",
        "views/stock_picking_views.xml",
    ],
    "installable": True,
    "application": False,
}
