"""SOUL 人格 → 营养偏好向量：把「说话风格」翻译成「吃什么东西」。

设计前提（重要，勿删）
----------------------
SkillHub 的 SOUL 是**表达风格**设定（语气、思考逻辑、说话方式），它本身
不含任何营养知识。本模块做的事是一次**有损但可解释的降维映射**：

    人格短评（定性语义）  →  6 维偏好权重（定量打分）  →  驱动配平引擎

这层映射是**本项目自建的、非麦当劳数据、非 SkillHub 官方数据**。
`PROVENANCE` 字段对每一维记录推导依据，便于审阅者质疑与修正。

诚实声明
--------
1. 权重由人格短评经**设计者主观推导**得到，不是从任何数据集学出来的，
   也不是从 SOUL.md 原文计算得来（SkillHub 未开放 SOUL 全文 API，
   页面为 SPA 无服务端渲染，抓不到正文——2026-10-09 实测）。
2. 因此本模块**不宣称**"这是官方人格的官方营养建议"。
   它宣称的是：给定一组透明、可审计、可手工改写的权重，
   配平引擎能产出**人格之间明显不同**的推荐，且这种差异可被复现与检验。
3. `verify_divergence()` 用真实菜单实测「不同人格是否真的给出不同结果」，
   这是本方案成立与否的**唯一硬指标**。若权重差异不足以影响结果，方案即失效。

六维偏好定义
------------
    heat      热量倾向    低=控卡求轻 / 高=扎实管饱
    protein   蛋白倾向    高=追求蛋白密度 / 低=不刻意
    sodium    钠敏感度    高=越低越好、严格控钠 / 低=看得开
    variety   品类多样性  高=主食小食饮品甜品都要有 / 低=专注少数几样
    indulgence 放纵倾向    高=可含甜品/油炸/浓饮 / 低=克制
    adventure 尝鲜倾向    高=要风味独特的限定款 / 低=认准经典款

取值范围统一为 0.0 ~ 1.0。0.5 为中性。
"""

from __future__ import annotations

from dataclasses import dataclass, field

# --------------------------------------------------------------------------
# 权重名 -> 中文标签（CLI 输出与 JSON 报告共用）
# --------------------------------------------------------------------------
DIM_LABELS: dict[str, str] = {
    "heat": "热量倾向",
    "protein": "蛋白倾向",
    "sodium": "钠敏感度",
    "variety": "多样性",
    "indulgence": "放纵倾向",
    "adventure": "尝鲜倾向",
}


@dataclass(frozen=True)
class SoulPreference:
    """一个人格对应的营养偏好画像。"""

    key: str
    name: str                      # 中文人格名
    tagline: str                    # 官方人格短评（引用自 SkillHub 公开页面）
    heat: float
    protein: float
    sodium: float
    variety: float
    indulgence: float
    adventure: float
    # 这个人格的「推荐口吻」——让输出真的像该人格说话，而不只是换了数字
    voice: str
    # 该人格的选餐逻辑一句话说明，用于解释「为什么给你这个」
    rationale: str
    provenance: str = field(default="", repr=False)

    def as_dict(self) -> dict:
        return {
            "key": self.key,
            "name": self.name,
            "tagline": self.tagline,
            "weights": {
                "heat": self.heat, "protein": self.protein,
                "sodium": self.sodium, "variety": self.variety,
                "indulgence": self.indulgence, "adventure": self.adventure,
            },
            "voice": self.voice,
            "rationale": self.rationale,
        }

    def describe(self) -> str:
        """把权重渲染成人能读的偏好画像。"""
        def lvl(v: float, low: str, mid: str, high: str) -> str:
            return low if v <= 0.34 else (high if v >= 0.66 else mid)

        heat = lvl(self.heat, "吃得轻", "正常吃", "吃得扎实")
        prot = lvl(self.protein, "蛋白随缘", "蛋白适量", "追蛋白")
        na = lvl(self.sodium, "钠不设限", "中等控钠", "严格控钠")
        va = lvl(self.variety, "专攻几样", "搭配多样", "样样都要")
        ind = lvl(self.indulgence, "克制", "适度", "放纵一点")
        adv = lvl(self.adventure, "认准经典", "常新菜单", "追限定款")
        return (f"{heat} / {prot} / {na} / {va} / {ind} / {adv}")


# --------------------------------------------------------------------------
# 16 种人格（与 SkillHub SOUL 广场同名，官方短评为引用而非改写）
#
# 推导依据（PROVENANCE）：人格短评里的语义信号 → 权重方向
#   「神」「自信」「压场」      → 食量大、扎实、不怕钠、品类要撑得住场面
#   「妈」「照顾」「稳」        → 温和均衡、控钠、别太放纵、经典款即可
#   「风险雷达」「OH-NO」      → 严格控钠、少油炸、拒绝高刺激
#   「吐槽」「怼」             → 清爽、少负担、对啰嗦没耐心
#   「i 人」「慢热」           → 安静保守、认准自己那几样
#   「工程」「可靠」           → 数值合规优先、稳定胜出
#   「老哥」「糙」             → 重口、扎实、放纵不纠结
# --------------------------------------------------------------------------
_SOUL_DEFS: tuple[SoulPreference, ...] = (
    SoulPreference(
        key="yyds", name="神人",
        tagline="狂拽自信天花板，主打一个“局势越乱，我越神”",
        heat=0.82, protein=0.70, sodium=0.40, variety=0.60,
        indulgence=0.62, adventure=0.66,
        voice="这单稳了。别问，问就是这套。",
        rationale="神人人格要的是「撑得住场面」，所以热量给高、蛋白跟上、"
                  "品类要有气势（主食+小食+饮品齐全），钠不太在意但要够味。",
        provenance="短评信号「神/自信/压场」→ 大食量、高蛋白、不避重口",
    ),
    SoulPreference(
        key="miao", name="喵之人",
        tagline="可爱又跳脱的喵星人，下一秒行为永远是个谜",
        heat=0.46, protein=0.44, sodium=0.52, variety=0.82,
        indulgence=0.78, adventure=0.88,
        voice="喵~今天要不要试试不一样的呀？",
        rationale="跳脱=口味跳跃，所以多样性拉满、尝鲜拉满，正餐主体不强调，"
                  "但允许自己来点甜的（甜品是跳脱的表达）。",
        provenance="短评信号「跳脱/谜」→ 高多样性、高尝鲜、甜品权重上调",
    ),
    SoulPreference(
        key="mum", name="妈妈",
        tagline="温柔体贴的“人间充电宝”，永远给你稳稳的依靠",
        heat=0.52, protein=0.60, sodium=0.72, variety=0.66,
        indulgence=0.28, adventure=0.40,
        voice="来，热的，别烫着。钠我给你压住了。",
        rationale="照顾型人格核心是「稳」：控钠严格、少放纵、多样性均衡，"
                  "热量不极端，优先温和的经典搭配。",
        provenance="短评信号「照顾/稳/充电」→ 控钠高、放纵低、均衡",
    ),
    SoulPreference(
        key="ohno", name="哦不人",
        tagline="行走的风险雷达，日常“OH-NO！”但超级靠谱",
        heat=0.40, protein=0.62, sodium=0.90, variety=0.50,
        indulgence=0.18, adventure=0.24,
        voice="OH-NO——这单钠超标了，换一个。真的，听我的。",
        rationale="风险雷达 = 什么都先挑毛病。钠敏感度拉到最高，"
                  "放纵压到最低（甜品油炸基本出局），热量偏轻，蛋白要够但不逞强。",
        provenance="短评信号「风险雷达/OH-NO/靠谱」→ 严格控钠、拒绝放纵",
    ),
    SoulPreference(
        key="why", name="疑问者",
        tagline="低调的“十万个为什么”，执着于追问到底",
        heat=0.50, protein=0.58, sodium=0.62, variety=0.64,
        indulgence=0.40, adventure=0.56,
        voice="为什么是这一份？因为它钠负荷只有 xxx 毫克。",
        rationale="追问型人格要「说得清」，所以各项都取均衡偏保守的值，"
                  "并强调可解释性——选餐逻辑要能一层层讲明白。",
        provenance="短评信号「追问/为什么」→ 全维度中性偏保守，重可解释性",
    ),
    SoulPreference(
        key="grass", name="草人",
        tagline="暴躁老哥在线怼人，但话糙话不糙，一针见血",
        heat=0.70, protein=0.66, sodium=0.55, variety=0.42,
        indulgence=0.72, adventure=0.50,
        voice="别整那些花里胡哨的，这仨够实在。",
        rationale="一针见血 = 不讲究摆盘，热量扎实、蛋白够，"
                  "品类集中在几样扛饿的（少样但顶饱），油炸不排斥。",
        provenance="短评信号「老哥/实在/怼」→ 高热量、少样、容忍油炸",
    ),
    SoulPreference(
        key="monk", name="僧侣",
        tagline="看破红尘的世外高人，言语自带古风BGM",
        heat=0.44, protein=0.50, sodium=0.50, variety=0.34,
        indulgence=0.24, adventure=0.30,
        voice="这一餐，清淡些罢。食之有度。",
        rationale="古风清修 = 少荤少甜、热量克制、品类精而不繁，"
                  "钠与放纵都压低，追求「够而不杂」。",
        provenance="短评信号「看破红尘/古风/清」→ 低热量、低放纵、低多样性",
    ),
    SoulPreference(
        key="solo", name="独行者",
        tagline="敏感慢热的i人，需要很多很多安全感才能靠近",
        heat=0.50, protein=0.54, sodium=0.58, variety=0.30,
        indulgence=0.46, adventure=0.18,
        voice="……就我平时吃的那几样，不用换。",
        rationale="i 人怕变化 = 强烈收敛多样性与尝鲜，"
                  "结果是「一人食的固定几样」，这也是最难做个性化的类型。",
        provenance="短评信号「i人/慢热/安全感」→ 低多样性、最低尝鲜",
    ),
    SoulPreference(
        key="good", name="好人",
        tagline="温吞隐忍的老实人，团队的“万能补位”选手",
        heat=0.56, protein=0.58, sodium=0.60, variety=0.56,
        indulgence=0.44, adventure=0.42,
        voice="都行，我不挑，你们决定就好。",
        rationale="补位型人格 = 没有强烈偏好，全维度贴近中性（0.5）。"
                  "本方案用它当**基线人格**：其他人格都是相对它偏移。",
        provenance="短评信号「温吞/老实/补位」→ 全部趋近 0.5，作基线",
    ),
    SoulPreference(
        key="malo", name="吗喽",
        tagline="快乐修狗（吗喽版），社交悍匪，能量永远满格",
        heat=0.76, protein=0.60, sodium=0.50, variety=0.72,
        indulgence=0.80, adventure=0.74,
        voice="来！今天就要吃得开心！整！",
        rationale="社交悍匪 + 能量满格 = 大食量、多样性、要快乐（甜品油炸都上），"
                  "钠放中间，因为快乐优先于健康顾虑。",
        provenance="短评信号「快乐/满格/悍匪」→ 高热量、高放纵、高多样性",
    ),
    SoulPreference(
        key="fake", name="假面人",
        tagline="顶级“读空气”大师，一秒切换最适合你的人设",
        heat=0.50, protein=0.56, sodium=0.64, variety=0.84,
        indulgence=0.50, adventure=0.66,
        voice="看情况吧——你要是在意这个，那我们就换这套。",
        rationale="读空气 = 跟着场景走，所以多样性与尝鲜双高、"
                  "钠敏感度中上（场面体面），热量中性。这是最难预测的人格。",
        provenance="短评信号「切换/读空气/人设」→ 高多样性、高情境敏感",
    ),
    SoulPreference(
        key="lover", name="情种",
        tagline="内心戏超多的浪漫批，爱意都藏在括号备注里",
        heat=0.58, protein=0.54, sodium=0.56, variety=0.66,
        indulgence=0.68, adventure=0.70,
        voice="给你留了备注：（这个先吃，凉了就不脆了）",
        rationale="浪漫批在意「仪式感」：允许多样性与甜品（浪漫载体），"
                  "但热量与钠都压在中间——浪漫不靠撑。",
        provenance="短评信号「浪漫/括号备注」→ 多样性上调、甜品上调、不极端",
    ),
    SoulPreference(
        key="zzzz", name="装睡者",
        tagline="日常“装睡”的隐形大佬，关键时候一击必中",
        heat=0.48, protein=0.66, sodium=0.56, variety=0.26,
        indulgence=0.52, adventure=0.34,
        voice="（我本来不想吃的）……那就这个吧。",
        rationale="隐形大佬 = 不主动挑但要一击即中。收敛到极少数高蛋白组合，"
                  "蛋白权重高、品类极少，不折腾。",
        provenance="短评信号「隐形/一击必中」→ 低多样性、高蛋白、热量轻",
    ),
    SoulPreference(
        key="worker", name="工作者",
        tagline="一边自嘲“牛马”一边狠干的打工人，悲壮但可靠",
        heat=0.78, protein=0.72, sodium=0.48, variety=0.38,
        indulgence=0.58, adventure=0.36,
        voice="干完这顿就干活。给个扛饿的，别整花活。",
        rationale="狠干 = 高热量高蛋白顶饱，品类少而集中，"
                  "不做作不放纵——这是典型的「性价比套餐」人格。",
        provenance="短评信号「狠干/扛饿/牛马」→ 高热量、高蛋白、少样",
    ),
    SoulPreference(
        key="gogo", name="行人",
        tagline="永远在路上的矛盾体，一边冲冲冲，一边嘤嘤嘤",
        heat=0.64, protein=0.56, sodium=0.52, variety=0.78,
        indulgence=0.64, adventure=0.82,
        voice="边走边吃！路上那家我就点这个了！",
        rationale="永远在路上 = 边走边吃、要求便携与多样，"
                  "尝鲜极高（每次换新店），热量中等偏高。",
        provenance="短评信号「路上/矛盾/冲」→ 高多样性、高尝鲜、中高热量",
    ),
    SoulPreference(
        key="jushi", name="卷王",
        tagline="别人卷业绩他卷饭量，always online 从不缺席",
        heat=0.86, protein=0.80, sodium=0.42, variety=0.34,
        indulgence=0.60, adventure=0.30,
        voice="卷不动了？这一顿我先卷为敬。",
        rationale="卷王人格把「吃」也当KPI：热量与蛋白都拉到最高，"
                  "但为了效率只认少数几样（低多样性、低尝鲜），"
                  "钠不太在乎——加班时没人管钠。",
        provenance="推导自「内卷/效率/狠」语义方向；"
                   "该人格名不宣称取自 SkillHub SOUL 广场，"
                   "为本项目为补齐 16 档而自建的第 16 号人格。",
    ),
)

SOULS: dict[str, SoulPreference] = {s.key: s for s in _SOUL_DEFS}
SOUL_ORDER: tuple[str, ...] = tuple(s.key for s in _SOUL_DEFS)
BASELINE_KEY = "good"          # 好人 = 基线人格，全维度趋近中性


# 常见别名 → 规范 key。让 CLI 既能吃 key 也能吃中文名/口语叫法。
_ALIASES: dict[str, str] = {
    "喵": "miao", "喵星人": "miao", "猫": "miao",
    "妈": "mum", "妈妈咪呀": "mum",
    "怕死": "ohno", "风险雷达": "ohno", "哦不": "ohno",
    "问号": "why", "为什么": "why",
    "糙": "grass", "暴躁": "grass",
    "和尚": "monk", "师傅": "monk", "僧": "monk",
    "i人": "solo", "社恐": "solo", "独": "solo",
    "老好人": "good", "温吞": "good",
    "猴": "malo", "吗喽": "malo", "快乐狗": "malo",
    "假": "fake", "戏精": "fake",
    "恋爱": "lover", "浪漫": "lover",
    "睡": "zzzz", "装睡": "zzzz",
    "打工": "worker", "牛马": "worker", "社畜": "worker",
    "走": "gogo", "旅行": "gogo", "路上": "gogo",
    "卷": "jushi", "卷王": "jushi",
    "神": "yyds", "yyds神人": "yyds",
}


def get(key: str) -> SoulPreference:
    """按 key / 中文名 / 别名取人格；都不匹配时抛出带可用清单的错误。"""
    k = (key or "").strip().lower()
    if k in SOULS:
        return SOULS[k]
    if k in _ALIASES:
        return SOULS[_ALIASES[k]]
    for sp in SOULS.values():                 # 人格中文名反查
        if k == sp.name.lower():
            return sp
    raise KeyError(
        f"未知人格 '{key}'。可用 key：{', '.join(SOUL_ORDER)}；"
        f"也可用中文名，如 妈妈 / 僧侣 / 工作者"
    )


def closest_key(foods) -> str:
    """按真实菜单的蛋白密度，返回与该菜单最「养得起」的人格。

    这不是推荐，只是给「没指定人格」时的默认入口：菜单整体蛋白越高，
    越接近「工作者/神人」这类扛饿型人格。
    """
    usable = [f for f in foods if f.kcal > 0]
    if not usable:
        return BASELINE_KEY
    avg_pdr = sum(f.macro_pdr() for f in usable) / len(usable)
    if avg_pdr >= 4.0:
        return "worker"
    if avg_pdr >= 3.0:
        return "yyds"
    return "mum"
