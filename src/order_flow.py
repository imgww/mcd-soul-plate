"""下单引导：把人格推荐结果翻译成「可下单清单」，并显式标注缺失字段。

设计立场（与平台契约一致，不可违背）
----------------------------------------
实测 `create-order` 的四个必需字段中，**三个不在营养表里**：

    storeCode          ← query-nearby-stores / delivery-query-stores
    takeWayCode        ← calculate-price 的 data.takeWayList[].code
    items[].productCode ← query-meals（门店菜单）
    orderType / beType  ← 可由用户选择

而本项目的营养数据源 `list-nutrition-foods` **只给中文菜名**。
因此第 1 步的推荐结果无法直接构造合法下单调用——这不是实现缺陷，是上游事实。

于是本模块的定位是**下游引导**，不是代下单：

    人格推荐（菜名 + 数量）
      → 匹配门店菜单拿 productCode
      → 核价拿实付与 takeWayCode
      → 交由用户确认后自行下单

默认状态下本模块**不会调用 create-order**。它只产出三样东西：

    1. 订单清单（菜名、数量、取餐方式）
    2. 缺口清单（还需要哪些字段、分别由哪个工具提供）
    3. 引导文案（用户接下来该做什么）

资损与确认纪律
--------------
* 默认 `plan_order()` 只走到「核价」为止，**永不自动下单**。
* 真实下单必须由用户显式开启（`OrderPlanner.allow_create_order`），
  且每次调用都要求传入 `confirmed_by_user=True`，否则拒绝执行。
* 不接入任何支付能力——支付在麦当劳侧，本项目只引导用户自行完成。
* 取消订单同样属于写操作，需用户主动请求，不主动发起。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence

from nutrition import Food

# 取餐方式（对应 beType / orderType 的官方取值）
BE_TYPES = {
    "pickup":    {"beType": 1, "orderType": 1, "label": "到店自取",
                  "needs_beCode": False, "needs_address": False,
                  "store_tool": "query-nearby-stores",
                  "desc": "到店自取，不传 beCode"},
    "dt":        {"beType": 5, "orderType": 1, "label": "得来速（车道取餐）",
                  "needs_beCode": True, "needs_address": False,
                  "store_tool": "query-nearby-stores",
                  "desc": "得来速，beCode 从 query-nearby-stores 获取"},
    "delivery":  {"beType": 2, "orderType": 2, "label": "麦乐送到家",
                  "needs_beCode": True, "needs_address": True,
                  "store_tool": "delivery-query-stores",
                  "desc": "外送，beCode 从 delivery-query-stores 获取，"
                          "还需 addressId"},
    "group":     {"beType": 6, "orderType": 2, "label": "企业团餐",
                  "needs_beCode": True, "needs_address": True,
                  "store_tool": "delivery-query-stores",
                  "desc": "团餐，beCode 从 delivery-query-stores 获取，"
                          "还需 addressId 与 gmServiceCode"},
}


@dataclass
class OrderItem:
    """订单里的一项。product_code 在匹配门店菜单之前为空。"""

    name: str
    quantity: int = 1
    kcal: float = 0.0
    product_code: str | None = None      # 需由 query-meals 填充
    note: str = ""


@dataclass
class Gap:
    """一个待补齐的字段缺口。"""

    field: str
    why: str
    provided_by: str
    who: str                         # user | tool

    def describe(self) -> str:
        return (f"{self.field}：{self.why}　"
                f"由 {'用户填写' if self.who == 'user' else provided_by} 提供")


@dataclass
class OrderPlan:
    """一份可下单清单。**它本身不是订单，也不代表已下单。**"""

    soul_key: str
    soul_name: str
    pickup: str
    items: list[OrderItem]
    gaps: list[Gap] = field(default_factory=list)
    quote: dict | None = None          # calculate-price 的返回（若有）
    guidance: list[str] = field(default_factory=list)

    @property
    def total_kcal(self) -> float:
        return sum(i.kcal * i.quantity for i in self.items)

    def is_ready(self) -> bool:
        """是否已具备构造下单调用的全部字段。"""
        return not self.gaps and all(i.product_code for i in self.items)

    def blocking_gaps(self) -> list[Gap]:
        """真正阻塞下单的缺口（区别于仅提示的信息缺口）。"""
        return [g for g in self.gaps if g.field in _BLOCKING_FIELDS]

    def as_dict(self) -> dict:
        return {
            "soul": {"key": self.soul_key, "name": self.soul_name},
            "pickup": {"mode": self.pickup, "label": BE_TYPES[self.pickup]["label"]},
            "items": [{"name": i.name, "quantity": i.quantity,
                       "kcal": round(i.kcal * i.quantity, 1),
                       "product_code": i.product_code,
                       "note": i.note} for i in self.items],
            "totals": {"kcal": round(self.total_kcal, 1), "items": len(self.items)},
            "gaps": [{"field": g.field, "why": g.why,
                      "provided_by": g.provided_by, "who": g.who}
                     for g in self.gaps],
            "ready_to_order": self.is_ready(),
            "quote": self.quote,
            "guidance": self.guidance,
            "disclaimer": "这是一份下单清单，不是已生成的订单；下单需用户确认后自行完成。",
        }


_BLOCKING_FIELDS = {"storeCode", "beCode", "items[].productCode", "takeWayCode"}


class OrderPlanner:
    """下单引导器。默认状态**永远不会**调用 create-order。"""

    def __init__(self, client=None, *,
                 allow_create_order: bool = False) -> None:
        self.client = client
        # 双保险：即使外部传 True，也必须每次调用都带 confirmed_by_user=True
        self.allow_create_order = bool(allow_create_order)
        self._create_order_calls: list[dict] = []

    # ---------- 阶段 1：产出清单（无网络调用） ----------

    def plan(self, foods: Sequence[Food], plan_items: Sequence[Food],
             soul_key: str, soul_name: str,
             pickup: str = "pickup",
             store_code: str | None = None,
             be_code: str | None = None,
             address_id: str | None = None) -> OrderPlan:
        """把推荐结果转成下单清单，并列出还缺什么。

        本方法**不发起任何 MCP 调用**，只做翻译与缺口分析。
        """
        if pickup not in BE_TYPES:
            raise ValueError(
                f"未知取餐方式 '{pickup}'，可用：{', '.join(BE_TYPES)}")
        spec = BE_TYPES[pickup]

        items = [OrderItem(name=f.name, quantity=1, kcal=f.kcal)
                 for f in plan_items]
        gaps: list[Gap] = []

        # 必填字段缺口
        if not store_code:
            gaps.append(Gap(
                "storeCode", "下单必填门店编码，但营养表不含门店信息",
                spec["store_tool"], "tool"))
        if spec["needs_beCode"] and not be_code:
            gaps.append(Gap(
                "beCode", f"{spec['label']}场景必传业务编码",
                spec["store_tool"], "tool"))
        gaps.append(Gap(
            "items[].productCode",
            "下单必填商品编码；营养表只有中文菜名，需从门店菜单匹配",
            "query-meals", "tool"))
        gaps.append(Gap(
            "takeWayCode" if spec["orderType"] == 1 else "—",
            "到店场景必填取餐方式码，来自核价返回",
            "calculate-price", "tool" if spec["orderType"] == 1 else "user"))

        if spec["needs_address"] and not address_id:
            gaps.append(Gap(
                "addressId", f"{spec['label']}必填配送地址 ID",
                "delivery-query-addresses", "user"))

        gaps = [g for g in gaps if g.field != "—"]

        return OrderPlan(
            soul_key=soul_key, soul_name=soul_name, pickup=pickup,
            items=items, gaps=gaps,
            guidance=self._guidance(spec, bool(gaps)),
        )

    # ---------- 阶段 2：只读核价（可选，需联网） ----------

    def quote(self, plan: OrderPlan, store_code: str,
              be_code: str | None = None,
              address_id: str | None = None,
              items: list[dict] | None = None) -> dict | None:
        """调用 calculate-price 核价。**只读，不下单。**"""
        if self.client is None:
            return None
        spec = BE_TYPES[plan.pickup]
        payload_items = items or [
            {"productCode": i.product_code, "quantity": i.quantity}
            for i in plan.items if i.product_code
        ]
        if not payload_items:
            return None
        args = {
            "storeCode": store_code,
            "orderType": spec["orderType"],
            "beType": spec["beType"],
            "items": payload_items,
        }
        if be_code:
            args["beCode"] = be_code
        if address_id:
            args["addressId"] = address_id
        try:
            plan.quote = self.client.call_tool("calculate-price", args)
            return plan.quote
        except Exception:                      # noqa: BLE001
            return None

    # ---------- 阶段 3：真实下单（需双重确认，默认关闭） ----------

    def create_order(self, *, store_code: str, order_type: int, be_type: int,
                     items: list[dict], confirmed_by_user: bool = False,
                     be_code: str | None = None,
                     take_way_code: str | None = None,
                     address_id: str | None = None,
                     remark: str | None = None) -> dict:
        """调用 create-order。**高风险写操作**，需显式确认。

        三道锁：
          1. 构造时 ``allow_create_order=True``
          2. 每次调用必须显式传 ``confirmed_by_user=True``
          3. 校验必需字段齐全，缺一即拒绝

        任一不满足都拒绝执行，不做任何"部分下单"。

        ``confirmed_by_user`` 默认 False 而非必填，是为了让"忘记传"这个
        最危险的场景走 PermissionError 的可读拒绝，而不是 TypeError。
        """
        if not self.allow_create_order:
            raise PermissionError(
                "下单能力未开启。本 Skill 默认不代下单；"
                "如确需开启，请显式传入 allow_create_order=True。")
        if confirmed_by_user is not True:
            raise PermissionError(
                "下单需用户明确确认。未收到确认，不会调用 create-order。")
        if not store_code:
            raise ValueError("下单失败：缺 storeCode")
        if not items:
            raise ValueError("下单失败：缺 items")
        for it in items:
            if not it.get("productCode"):
                raise ValueError(
                    f"下单失败：items 中「{it.get('name', '未命名')}」缺 productCode")

        spec = next((s for s in BE_TYPES.values()
                     if s["orderType"] == order_type and s["beType"] == be_type), None)
        args = {"storeCode": store_code, "orderType": order_type,
                "beType": be_type, "items": items}
        if spec and spec["needs_beCode"]:
            if not be_code:
                raise ValueError("下单失败：该场景必传 beCode")
            args["beCode"] = be_code
        if order_type == 1 and not take_way_code:
            raise ValueError("下单失败：到店场景必传 takeWayCode")
        if take_way_code:
            args["takeWayCode"] = take_way_code
        if address_id:
            args["addressId"] = address_id
        if remark:
            if len(remark) > 50:
                raise ValueError("下单失败：备注最多 50 字")
            args["remark"] = remark

        result = self.client.call_tool("create-order", args)
        self._create_order_calls.append(args)
        return result

    @property
    def create_order_call_count(self) -> int:
        """已发生的真实下单次数，用于审计与测试。"""
        return len(self._create_order_calls)

    # ---------- 引导文案 ----------

    def _guidance(self, spec: dict, has_gaps: bool) -> list[str]:
        lines = [
            f"取餐方式：{spec['label']}（{spec['desc']}）",
        ]
        if has_gaps:
            lines.append(
                "本 Skill 不代为下单。补齐下列字段后，在 MCP 客户端里"
                "由你确认并提交，或直接在麦当劳 App 完成下单：")
        else:
            lines.append(
                "字段已齐全。下单仍需你在客户端确认后执行——"
                "本 Skill 不会自动下单：")
        lines.append(
            "下单后可通过支付链接或麦当劳 App 完成支付；"
            "支付完成后回复「支付完成」，可用 query-order 回查订单状态。")
        return lines

    # ---------- 门店菜单匹配（需联网，只读） ----------

    def match_menu(self, store_code: str, order_type: int, be_type: int,
                   be_code: str | None = None) -> list[dict]:
        """拉取门店菜单，返回 [{name, productCode, price}]。**只读。**"""
        if self.client is None:
            return []
        args = {"storeCode": store_code, "orderType": order_type,
                "beType": be_type}
        if be_code:
            args["beCode"] = be_code
        try:
            return self.client.call_tool("query-meals", args) or []
        except Exception:                      # noqa: BLE001
            return []

    @staticmethod
    def match_items(plan: OrderPlan, menu: list[dict]) -> tuple[int, list[str]]:
        """用门店菜单回填 productCode。返回 (命中数, 未命中菜名列表)。

        名称匹配策略：精确匹配优先，其次去括号后缀再次，最后包含匹配。
        匹配不到就如实报告未命中，**不做模糊猜测**——猜错编码会导致下单失败
        或下错商品。
        """
        def norm(s: str) -> str:
            s = str(s).strip()
            for sep in ("（", "("):
                if sep in s:
                    s = s.split(sep)[0].strip()
            return s

        index: dict[str, str] = {}
        for row in menu or []:
            nm = row.get("name") or row.get("productName")
            code = row.get("productCode") or row.get("code")
            if nm and code:
                index[norm(nm)] = code

        hit = 0
        missed: list[str] = []
        for it in plan.items:
            code = index.get(norm(it.name))
            if not code:
                code = next((c for n, c in index.items()
                             if n and (n in norm(it.name) or norm(it.name) in n)), None)
            if code:
                it.product_code = code
                hit += 1
            else:
                missed.append(it.name)
        return hit, missed
