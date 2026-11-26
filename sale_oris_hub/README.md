# Sale ORIS HUB

Module Odoo 18 tích hợp giao hàng với các API bên ngoài thông qua ORIS HUB và
Odoo `delivery.carrier`. Hiện tại module triển khai provider GHTK; cấu trúc dùng
dispatch theo `delivery_type` của Odoo để có thể bổ sung provider khác.

> **Phạm vi hiện tại:** GHTK đã có implementation. Các field request, payload,
> response mapping và luồng xử lý vẫn đang đặc thù GHTK. Chưa thể thêm một hãng
> vận chuyển hoàn toàn chỉ bằng cấu hình mà không viết code provider.

## Chức năng hiện có

- Thêm trường Phường/Xã (`res.partner.ward`) để dùng với địa chỉ Việt Nam 2 cấp.
- Thêm provider `GHTK` vào `delivery.carrier`.
- Cấu hình Partner lấy hàng và ba request ORIS HUB trên Carrier:
  - Lấy phí.
  - Tạo vận đơn.
  - Hủy vận đơn.
- Lấy cước khi Odoo tính phí giao hàng cho Sale Order.
- Tạo vận đơn từ Delivery Order (`stock.picking`) qua `send_to_shipper()`.
- Hủy vận đơn GHTK khi hủy Delivery Order.
- Lưu trạng thái vận chuyển, mã vận đơn, phí, response và thời điểm gửi/hủy.
- Dùng số lượng thực giao (`stock.move.quantity`) trong payload; hỗ trợ gửi phần
  hàng đã giao và xử lý phần còn lại bằng backorder Odoo.

## Phụ thuộc

Manifest phụ thuộc:

```text
stock_delivery
oris_hub
```

`stock_delivery` phụ thuộc `sale_stock` và `delivery`, đồng thời bổ sung carrier
vào Delivery Order.

## Cài đặt

1. Đảm bảo thư mục `custom_addons` nằm trong `addons_path`.
2. Cập nhật Apps List.
3. Cài **Sale ORIS HUB**.
4. Cấu hình ba `hub.request` cho GHTK trước khi dùng Carrier.

Khi cập nhật code của module đã cài, upgrade module `sale_oris_hub`.

## Cấu hình ORIS HUB

Tạo hoặc cấu hình ba request. Code mặc định được khai báo trên Carrier:

| Thao tác | Request code mặc định | HTTP method | Endpoint |
|---|---|---|---|
| Lấy phí | `ORIS_GET_GHTK_FEE` | GET | `/services/shipment/fee` |
| Tạo đơn | `ORIS_CREATE_GHTK_ORDER` | POST | `/services/shipment/order/?ver=1.5` |
| Hủy đơn | `ORIS_CANCEL_GHTK_ORDER` | POST | `/services/shipment/cancel/{TRACKING_ORDER}` |

Các request cần dùng đúng Flow/Company để `_find_request_by_code()` phân giải
được request khi Carrier chạy. Cấu hình thông tin xác thực GHTK trong header của
request/Flow theo cách đang dùng tại môi trường cài đặt; không lưu token trong
source code hoặc README.

Request GHTK cần có các header xác thực theo tài khoản của bạn:

```http
Token: <GHTK API token>
X-Client-Source: <GHTK client source>
Content-Type: application/json
```

### Request lấy phí

- Response Data Type: JSON.
- Body: không cần.
- Truyền query parameters:

```text
province      = Tỉnh/Thành nơi giao
district      = Phường/Xã nơi giao (theo API fee đang dùng)
pick_province = Tỉnh/Thành nơi lấy
pick_ward     = Phường/Xã nơi lấy
weight        = Tổng trọng lượng, gram
```

Request code có thể đổi trong cấu hình Carrier. Provider hiện đọc response dạng:

```json
{
  "success": true,
  "fee": {
    "fee": 23540,
    "insurance_fee": 0,
    "delivery": true
  }
}
```

### Request tạo đơn

- Method: POST.
- Body Type: JSON.
- Response Data Type: JSON.
- Provider truyền payload GHTK vào runtime `BODY`.
- Response provider hiện dùng `success` và các trường trong `order`, gồm
  `label`, `tracking_id`, `fee`, `insurance_fee`.

### Request hủy đơn

- Method: POST.
- Body Type: None.
- Response Data Type: JSON.
- Endpoint:

```text
/services/shipment/cancel/{TRACKING_ORDER}
```

ORIS HUB thay `{TRACKING_ORDER}` bằng runtime value `TRACKING_ORDER`. Provider
truyền `stock.picking.carrier_tracking_ref`, thường là `tracking_id` do response
tạo đơn trả về.

## Cấu hình Delivery Carrier

Tạo Delivery Method trong Odoo và đặt:

```text
Provider: GHTK
GHTK Pickup Partner: Partner kho/shop lấy hàng
GHTK Fee Request Code: ORIS_GET_GHTK_FEE
GHTK Create Request Code: ORIS_CREATE_GHTK_ORDER
GHTK Cancel Request Code: ORIS_CANCEL_GHTK_ORDER
GHTK Tracking URL: URL theo dõi, có thể dùng <shipmenttrackingnumber>
```

Partner lấy hàng và Partner giao hàng cần có:

- Country là Việt Nam.
- Province/City (`state_id`).
- Phường/Xã (`ward`).
- Số điện thoại hoặc di động.
- Địa chỉ (`street`/`street2`).

Partner lấy hàng được cấu hình trên Carrier. Partner giao hàng được lấy từ địa
chỉ giao của Sale Order/Delivery Order.

Sản phẩm cần có khối lượng lớn hơn 0. Khối lượng sản phẩm Odoo tính bằng kg;
request phí đổi tổng khối lượng sang gram. API tạo đơn nhận `weight` theo kg.

## Luồng sử dụng

### Tính phí trên Sale Order

1. Chọn Delivery Method GHTK trên Sale Order.
2. Odoo gọi `delivery.carrier.rate_shipment()`.
3. Odoo dispatch đến `ghtk_rate_shipment(order)`.
4. Provider gọi fee request trong ORIS HUB và trả phí về Delivery Carrier.

### Tạo vận đơn

1. Xác nhận Sale Order để tạo Delivery Order.
2. Đảm bảo picking có carrier GHTK và ở trạng thái Ready (`assigned`).
3. Nhập số lượng thực giao trong thao tác kho nếu chỉ giao một phần.
4. Nhấn **Send to GHTK**.
5. Odoo gọi `stock.picking.send_to_shipper()`; `delivery.carrier` dispatch đến
   `ghtk_send_shipping(pickings)`.
6. Provider gọi request tạo đơn, lưu tracking reference, phí và response.

Payload sản phẩm lấy từ các move có `quantity > 0`. Khi giao thiếu, chỉ phần
quantity thực giao được gửi. Validate picking theo luồng kho chuẩn để Odoo tạo
backorder; backorder có picking number riêng và có thể gửi thành vận đơn tiếp
theo khi sẵn sàng.

### Hủy vận đơn

Khi hủy picking đã có tracking reference, module gọi
`delivery.carrier.cancel_shipment()` và dispatch đến `ghtk_cancel_shipment()`.
Nếu API GHTK từ chối, thao tác hủy picking bị chặn bằng lỗi.

## Mở rộng thêm nhà vận chuyển

Odoo `stock_delivery` dispatch provider theo tên phương thức dựa trên
`delivery_type`, ví dụ:

```python
getattr(carrier, "%s_send_shipping" % carrier.delivery_type)
```

Provider tiếp theo có thể bổ sung các phương thức cùng interface:

```text
<provider>_rate_shipment(order)
<provider>_send_shipping(pickings)
<provider>_cancel_shipment(pickings)
<provider>_get_tracking_link(picking)
```

Tuy vậy, implementation hiện tại chưa phải framework carrier cấu hình hoàn toàn
động: thêm Viettel Post, Tiki hoặc hãng khác vẫn cần provider code và phần
mapping/response tương ứng. Mục tiêu cấu hình mọi hãng chỉ bằng `hub.request`
cần một lớp request/mapping/response tổng quát và giao diện cấu hình riêng; đó
chưa nằm trong phạm vi phiên bản hiện tại.

## Mã nguồn chính

```text
models/delivery_carrier.py       Provider GHTK, mapping và gọi hub.request
models/stock_picking.py          Trạng thái vận chuyển, gửi và hủy từ picking
models/res_partner.py            Trường ward trên res.partner
views/delivery_carrier_views.xml Cấu hình GHTK trên Delivery Carrier
views/stock_picking_views.xml    Nút gửi và thông tin vận đơn
```
