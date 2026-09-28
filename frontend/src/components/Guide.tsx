import { useEffect, useMemo, useState } from "react";
import { Card, Empty, Select, Spin, Tabs, Tag } from "antd";
import {
  EnvironmentOutlined,
  PhoneOutlined,
  StarFilled,
} from "@ant-design/icons";
import AttractionImage from "./AttractionImage";

interface GuideCity {
  province: string;
  city: string;
}

interface Attraction {
  name: string;
  lat?: number | null;
  lng?: number | null;
  rating?: number | null;
  price_tier?: number | null;
  description?: string;
  tags?: string[];
  // 高德真实景点：照片直链（优于必应搜索图）
  photo_url?: string | null;
}

interface AmapItem {
  name: string;
  address?: string | null;
  tel?: string | null;
  photo_url?: string | null;
  lat?: number;
  lng?: number;
}

interface GuideData {
  city: string;
  attractions: Attraction[];
  restaurants: AmapItem[];
  hotels: AmapItem[];
  amap_available: boolean;
}

const PRICE_TIERS = ["", "¥", "¥¥", "¥¥¥", "¥¥¥¥"];

function PriceTier({ tier }: { tier?: number | null }) {
  const n = typeof tier === "number" ? tier : 0;
  return n > 0 && n <= 4 ? (
    <span className="text-xs text-slate-500">{PRICE_TIERS[n]}</span>
  ) : null;
}

function AmapCard({ item }: { item: AmapItem }) {
  return (
    <Card size="small" className="h-full">
      <div className="font-medium text-slate-800">{item.name}</div>
      <div className="mt-2">
        <AttractionImage name={item.name} photoUrl={item.photo_url ?? undefined} />
      </div>
      {item.address && (
        <div className="mt-2 flex items-center gap-1 text-xs text-slate-500">
          <EnvironmentOutlined className="text-brand" />
          <span className="truncate">{item.address}</span>
        </div>
      )}
      {item.tel && (
        <div className="mt-1 flex items-center gap-1 text-xs text-slate-500">
          <PhoneOutlined className="text-brand" />
          <span>{item.tel}</span>
        </div>
      )}
    </Card>
  );
}

export default function Guide() {
  const [cities, setCities] = useState<GuideCity[]>([]);
  const [city, setCity] = useState<string>("");
  const [data, setData] = useState<GuideData | null>(null);

  // 加载可选城市（不 setState 默认值：城市列表加载完成后由派生值自动生效）
  useEffect(() => {
    fetch("/api/guide/cities")
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => setCities(d?.cities ?? []))
      .catch(() => {});
  }, []);

  // 当前城市：用户显式选择优先；未选时默认第一个城市（派生值，无额外渲染）
  const activeCity = city || cities[0]?.city || "";

  // 城市切换 → 拉取攻略（cancelled 标记：旧请求的响应不得覆盖新城市）
  const [loadedCity, setLoadedCity] = useState("");
  useEffect(() => {
    if (!activeCity) return;
    let cancelled = false;
    fetch(`/api/guide?city=${encodeURIComponent(activeCity)}`)
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => {
        if (!cancelled) {
          setData(d);
          setLoadedCity(activeCity);
        }
      })
      .catch(() => {
        if (!cancelled) setData(null);
      });
    return () => {
      cancelled = true;
    };
  }, [activeCity]);

  // 加载中：数据未到，或请求的城市与已加载城市不一致（切换瞬间）
  const loading = data === null || loadedCity !== activeCity;

  // 按省分组的城市选项
  const cityOptions = useMemo(() => {
    const map = new Map<string, { label: string; value: string }[]>();
    for (const c of cities) {
      if (!map.has(c.province)) map.set(c.province, []);
      map.get(c.province)!.push({ label: c.city, value: c.city });
    }
    return [...map.entries()].map(([province, options]) => ({
      label: province,
      options,
    }));
  }, [cities]);

  return (
    <div className="mx-auto max-w-4xl p-4 md:p-6">
      <h2 className="mb-1 text-lg font-semibold text-slate-800">攻略浏览</h2>
      <p className="mb-4 text-sm text-slate-500">
        按城市浏览景点、美食与住宿（景点/美食/住宿均来自高德地图，无高德数据时景点回退知识库）
      </p>

      <Select
        className="mb-4 w-64"
        showSearch
        placeholder="选择城市"
        value={activeCity || undefined}
        onChange={setCity}
        options={cityOptions}
        optionFilterProp="label"
      />

      {loading ? (
        <div className="flex justify-center py-16">
          <Spin />
        </div>
      ) : data ? (
        <Tabs
          items={[
            {
              key: "attractions",
              label: `景点 (${data.attractions.length})`,
              children:
                data.attractions.length === 0 ? (
                  <Empty description="该城市暂无景点数据" />
                ) : (
                  <div className="grid gap-4 sm:grid-cols-2">
                    {data.attractions.map((a, i) => (
                      <Card key={i} size="small" className="h-full">
                        <div className="flex items-center justify-between gap-2">
                          <span className="font-medium text-slate-800">
                            {a.name}
                          </span>
                          <span className="flex shrink-0 items-center gap-2">
                            <PriceTier tier={a.price_tier} />
                            {a.rating != null && (
                              <span className="flex items-center gap-0.5 text-sm text-amber-500">
                                <StarFilled />
                                {a.rating}
                              </span>
                            )}
                          </span>
                        </div>
                        <div className="mt-2">
                          <AttractionImage
                            name={a.name}
                            city={city}
                            photoUrl={a.photo_url ?? undefined}
                          />
                        </div>
                        {a.tags?.length ? (
                          <div className="mt-2 flex flex-wrap gap-1">
                            {a.tags.map((t) => (
                              <Tag key={t} color="cyan">
                                {t}
                              </Tag>
                            ))}
                          </div>
                        ) : null}
                        {a.description && (
                          <p className="mt-2 text-sm leading-relaxed text-slate-600">
                            {a.description}
                          </p>
                        )}
                      </Card>
                    ))}
                  </div>
                ),
            },
            {
              key: "restaurants",
              label: `美食 (${data.restaurants.length})`,
              children: !data.amap_available ? (
                <Empty description="未配置高德地图 key，美食数据不可用" />
              ) : data.restaurants.length === 0 ? (
                <Empty description="该城市暂无美食数据" />
              ) : (
                <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
                  {data.restaurants.map((r, i) => (
                    <AmapCard key={i} item={r} />
                  ))}
                </div>
              ),
            },
            {
              key: "hotels",
              label: `住宿 (${data.hotels.length})`,
              children: !data.amap_available ? (
                <Empty description="未配置高德地图 key，住宿数据不可用" />
              ) : data.hotels.length === 0 ? (
                <Empty description="该城市暂无住宿数据" />
              ) : (
                <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
                  {data.hotels.map((h, i) => (
                    <AmapCard key={i} item={h} />
                  ))}
                </div>
              ),
            },
          ]}
        />
      ) : null}
    </div>
  );
}
