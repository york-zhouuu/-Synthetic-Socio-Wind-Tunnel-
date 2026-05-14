## ADDED Requirements

### Requirement: Atlas SHALL expose typed convenience accessors for workplaces and POIs

`synthetic_socio_wind_tunnel.atlas.service.Atlas` SHALL 在已有
`list_buildings_by_type(building_type)` 和 `list_residential_buildings()`
之上新增两个便利方法：

- `list_workplaces() -> list[Building]`：返回 `building_type ∈ {office,
  school, commercial, community, hospital}` 的所有 Building；
- `list_pois() -> dict[str, list[Building | OutdoorArea]]`：返回按 POI
  category 分组的字典，key ∈ {"food_drink", "shop", "leisure", "civic"}，
  value 是该类的 Building / OutdoorArea 列表：
  - `food_drink`: building_type ∈ {cafe, restaurant, bar}
  - `shop`: building_type == "shop"
  - `leisure`: building_type ∈ {entertainment, hotel, worship} ∪
    outdoor area_type ∈ {park, playground, garden}
  - `civic`: building_type == "community"

两方法 SHALL 是 pure 读 atlas region；O(N) 一次扫描可；语义不修改任何
已有数据。

#### Scenario: list_workplaces 返回正确类型
- **WHEN** 在 Lane Cove atlas 上调 `atlas.list_workplaces()`
- **THEN** 返回 list 中每个 Building 的 `building_type` SHALL ∈
  {office, school, commercial, community, hospital}；
  SHALL 不含 `building_type == "residential"` 的 Building

#### Scenario: list_pois 分组完整
- **WHEN** 在 Lane Cove atlas 上调 `atlas.list_pois()`
- **THEN** 返回 dict SHALL 含 4 个 key（"food_drink", "shop", "leisure",
  "civic"）；每个 value SHALL 是非空 list（Lane Cove 各类都有实例）；
  "leisure" value 中 SHALL 同时含 Building 和 OutdoorArea 实例

#### Scenario: residential 建筑不出现在 workplaces / pois
- **WHEN** Lane Cove atlas 上调 list_workplaces 和 list_pois
- **THEN** 两返回的所有 Building id SHALL 与 `list_residential_buildings()`
  返回的 id 集合 disjoint

### Requirement: Atlas typed accessors SHALL return deterministically ordered results

Atlas typed accessors SHALL return results in deterministic order. The
methods `list_workplaces()`, `list_pois()`, `list_residential_buildings()`,
and `list_buildings_by_type()` MUST sort their results by building id
alphabetically; repeat calls on the same atlas MUST yield byte-equal output.

#### Scenario: 两次调用输出相同
- **WHEN** 在同 atlas 上分别调 `atlas.list_workplaces()` 两次
- **THEN** 两次返回的 Building id 列表 SHALL 顺序相同（按 id 字母序）
