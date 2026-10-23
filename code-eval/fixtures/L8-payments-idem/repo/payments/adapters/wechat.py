"""微信支付渠道适配器（示例）。"""


class WechatClient:
    def __init__(self, mch_id):
        self.mch_id = mch_id

    def unified_order(self, amount_cents, body):
        return {"channel": "wechat", "amount_cents": amount_cents, "body": body}
