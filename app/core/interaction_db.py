"""药物相互作用数据库（CSV 版）：名称归一化、查找、风险分级。"""
from __future__ import annotations

import csv
from typing import Dict, List

from app.config import INTERACTIONS_CSV

_SUFFIXES = ["缓释胶囊", "缓释片", "肠溶胶囊", "肠溶片", "咀嚼片", "分散片",
             "泡腾片", "口服溶液", "口服液", "混悬滴剂", "混悬液", "颗粒",
             "钙片", "钠片", "镁片", "钾片", "胶囊", "片",
             "滴剂", "气雾剂", "糖浆", "软胶囊", "栓", "滴眼液", "贴片"]


# 类别泛称 -> 该类别下的具体药名（仅收录知识库/相互作用表中确实存在的代表药）。
# 让「头孢类抗生素能同服吗」这类泛称提问也能落到具体药对查询上。
# 键必须是完整的类别词组（含「类」），避免药名本身（如「头孢呋辛酯片」）误触发。
CLASS_ALIASES: Dict[str, List[str]] = {
    "头孢类": ["头孢呋辛酯片", "头孢克肟分散片"],
    "头孢菌素类": ["头孢呋辛酯片", "头孢克肟分散片"],
    "喹诺酮类": ["左氧氟沙星片", "莫西沙星片", "环丙沙星片"],
    "氟喹诺酮类": ["左氧氟沙星片", "莫西沙星片", "环丙沙星片"],
    "他汀类": ["阿托伐他汀钙片", "辛伐他汀片", "洛伐他汀胶囊", "普伐他汀钠片"],
    "大环内酯类": ["红霉素肠溶片", "克拉霉素片", "阿奇霉素分散片"],
    "磺脲类": ["格列本脲片", "格列吡嗪片"],
    "安眠药": ["艾司唑仑片", "地西泮片"],
    "抗抑郁药": ["氟西汀胶囊", "帕罗西汀片", "舍曲林片"],
}


def short_name(name: str) -> str:
    """去掉剂型后缀得到短名，如 布洛芬缓释胶囊 -> 布洛芬。"""
    for s in _SUFFIXES:
        if name.endswith(s) and len(name) > len(s):
            return name[: -len(s)]
    return name


def distinct_drugs(names: List[str]) -> List[str]:
    """按短名去重，保留每个成分首次出现的名字（顺序不变）。

    同一成分的多个剂型（布洛芬缓释胶囊 / 布洛芬片）互为同一味药，
    若不去重会让「药对」退化成单药自配对，导致相互作用查询恒不命中。
    """
    seen, out = set(), []
    for n in names:
        key = short_name(n)
        if key in seen:
            continue
        seen.add(key)
        out.append(n)
    return out


class InteractionDB:
    """加载 interactions.csv，支持按药品名双向匹配。"""

    def __init__(self, path=INTERACTIONS_CSV):
        self.rows: List[Dict] = []
        self._names: List[str] = []  # 排序后的全部规范药名（缓存，避免每次排序）
        self._short_index: Dict[str, List[str]] = {}  # 短名 -> 规范名列表
        self._pair_index: Dict[frozenset, List[Dict]] = {}  # 短名对 -> 相互作用记录
        if path.exists():
            with open(path, encoding="utf-8-sig") as f:
                self.rows = list(csv.DictReader(f))
            names = set()
            for r in self.rows:
                names.update((r["drug_a"], r["drug_b"]))
                self._pair_index.setdefault(
                    frozenset([short_name(r["drug_a"]), short_name(r["drug_b"])]),
                    []).append(r)
            self._names = sorted(names)
            for name in names:
                self._short_index.setdefault(short_name(name), []).append(name)

    def all_names(self) -> List[str]:
        return self._names

    def find_drugs(self, text: str) -> List[str]:
        """返回文本中命中的规范药品名（长名优先）。

        识别三类写法：① 完整药名（布洛芬缓释胶囊）；② 短名（布洛芬，补全为全部剂型）；
        ③ 类别泛称（头孢类抗生素 -> 该类别下的具体药）。泛称结果追加在末尾，
        不参与排序，避免压过用户明确点名的药。
        """
        hit_names = set()
        for name in self._names:
            if name in text:
                hit_names.add(name)
        # 短名匹配（避免漏检如"布洛芬"）
        for sname, names in self._short_index.items():
            if sname in text and sname not in hit_names:
                hit_names.update(names)
        ordered = sorted(hit_names, key=lambda n: -len(n))

        alias_hits: List[str] = []
        known = set(self._names)
        for phrase, members in CLASS_ALIASES.items():
            if phrase not in text:
                continue
            for m in members:
                if m in known and m not in alias_hits and m not in hit_names:
                    alias_hits.append(m)
        return ordered + sorted(alias_hits, key=lambda n: -len(n))

    def lookup(self, a: str, b: str) -> List[Dict]:
        """查找 a、b 两药（任意顺序）的全部相互作用记录。O(1) 短名对索引。"""
        return self._pair_index.get(frozenset([short_name(a), short_name(b)]), [])

    def lookup_many(self, drugs: List[str]) -> List[Dict]:
        """在一组药品内两两匹配。"""
        seen, out = set(), []
        for i in range(len(drugs)):
            for j in range(i + 1, len(drugs)):
                for r in self.lookup(drugs[i], drugs[j]):
                    key = r["drug_a"] + "|" + r["drug_b"]
                    if key not in seen:
                        seen.add(key)
                        out.append(r)
        return out


_db: InteractionDB | None = None


def get_interaction_db() -> InteractionDB:
    global _db
    if _db is None:
        _db = InteractionDB()
    return _db


def risk_text(level: str) -> str:
    return {"高": "高风险（禁止或强烈不建议合用）",
            "中": "中风险（慎用，需医生评估）",
            "低": "低风险（一般安全，注意观察）"}.get(level, "未知风险")
