## ADDED Requirements

### Requirement: Overture place category SHALL be classified via direct lookup

`Importer._infer_building_type` SHALL classify Overture place category values
via direct dictionary lookup before falling through to OSM amenity/shop/building
inference. The lookup SHALL handle values like `"cafe"`, `"restaurant"`,
`"bar"`, `"pub"`, `"church_cathedral"`, `"library"`, `"school"`,
`"kindergarten"`, `"hospital"`, `"clinic"`, `"office"`, `"real_estate_agent"`
as they appear in `properties["overture:place:category"]` (not prefix-split).

The mapping `_OVERTURE_CATEGORY_TO_TYPE` SHALL be exhaustive for the common
Overture Places categories observed in the Lane Cove enriched dataset, with
at minimum:
- food_drink: cafe, restaurant, fast_food_restaurant, pizza_place,
  bakery, coffee_shop, japanese_restaurant, italian_restaurant,
  chinese_restaurant, thai_restaurant, indian_restaurant, breakfast_restaurant
  → cafe/restaurant respectively
- bar/pub: bar, pub, wine_bar, beer_garden → bar
- shop: shop, supermarket, convenience_store, real_estate_agent (when not office),
  hair_salon, pharmacy → shop
- school: school, kindergarten, university, college → school
- hospital: hospital, clinic, dentist, medical_center → hospital
- worship: church_cathedral, mosque, synagogue, temple → worship
- office: office (when not retail), professional_services, advertising_agency → office
- community: library, community_centre, community_center → community
- entertainment: entertainment, cinema, theatre → entertainment

The lookup SHALL be case-sensitive matching Overture exact category values.

#### Scenario: cafe Overture category classified as cafe
- **WHEN** `_infer_building_type({"overture:place:category": "cafe", "building": "warehouse"})`
- **THEN** SHALL return `"cafe"` (not "industrial" from building tag)

#### Scenario: restaurant with warehouse building tag classified as restaurant
- **WHEN** `_infer_building_type({"overture:place:category": "restaurant", "building": "warehouse"})`
- **THEN** SHALL return `"restaurant"`

#### Scenario: church_cathedral classified as worship
- **WHEN** `_infer_building_type({"overture:place:category": "church_cathedral"})`
- **THEN** SHALL return `"worship"`

#### Scenario: kindergarten classified as school
- **WHEN** `_infer_building_type({"overture:place:category": "kindergarten"})`
- **THEN** SHALL return `"school"`

#### Scenario: unknown category falls back to legacy chain
- **WHEN** `_infer_building_type({"overture:place:category": "unknown_xyz",
  "amenity": "cafe"})`
- **THEN** SHALL return `"cafe"` (fell through to amenity)

### Requirement: Affordance-aware reclassification MUST upgrade building type

`Importer` SHALL apply affordance-aware reclassification AFTER initial
classification. When the initial building_type is in
`{utility, industrial, residential, unknown}` BUT the building's affordances
contain entries with category in `{cafe, coffee_shop, restaurant,
fast_food_restaurant, pizza_place, japanese_restaurant, italian_restaurant,
bar, pub, wine_bar}`, the building_type MUST be reclassified to the
corresponding type (cafe / restaurant / bar).

Affordance category is read from `affordance.description` text or from a
`category` field in the raw affordance dict (the importer's affordance
extraction SHALL preserve this category info).

#### Scenario: warehouse with cafe affordance reclassified
- **WHEN** importing a building with `building: "warehouse"` and
  `affordances: [{"category": "cafe", "name": "Mowbray Eatery"}]`
- **THEN** final `building_type` SHALL be `"cafe"` (not "industrial")

#### Scenario: residential with restaurant affordance reclassified
- **WHEN** importing a building with `building: "house"` and
  `affordances: [{"category": "restaurant", "name": "Sake Ichiban"}]`
- **THEN** final `building_type` SHALL be `"restaurant"` (not "residential")

#### Scenario: cafe building unchanged by affordance reclassification
- **WHEN** building already has `building_type == "cafe"` from initial pass
- **THEN** affordance pass SHALL NOT change it

### Requirement: Lane Cove atlas SHALL have at least 25 cafe and 20 restaurant buildings

The production Lane Cove atlas MUST contain realistic POI density after the
new Overture category + affordance-aware reclassification is applied. When
built from `data/lanecove_enriched.geojson`, the atlas SHALL contain:
- ≥ 20 buildings with `building_type == "cafe"`
- ≥ 20 buildings with `building_type == "restaurant"`
- ≥ 2 buildings with `building_type == "bar"`

This reflects the realistic POI density of a Sydney middle-density suburb
(25 cafe / 20 restaurant / ~3 bar in Lane Cove 2066 confirmed via OSM
amenity + Overture Places audits).

#### Scenario: Lane Cove atlas POI counts meet realism threshold
- **WHEN** `Atlas.from_json("data/lanecove_atlas.json")` is loaded after
  importer fixes applied
- **THEN** `len(atlas.list_buildings_by_type("cafe"))` SHALL be ≥ 20;
  `len(atlas.list_buildings_by_type("restaurant"))` SHALL be ≥ 20;
  `len(atlas.list_buildings_by_type("bar"))` SHALL be ≥ 2
