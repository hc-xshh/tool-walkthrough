"""支付宝渠道适配器（示例，不参与主流程）。"""


class AlipayClient:
    def __init__(self, app_id):
        self.app_id = app_id

    def pay(self, amount_cents, subject):
        return {"channel": "alipay", "amount_cents": amount_cents, "subject": subject}
