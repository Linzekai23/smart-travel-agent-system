import { useState } from "react";
import { Alert, Button, Card, Input, Radio, Spin } from "antd";
import {
  CarOutlined,
  CompassOutlined,
  EnvironmentOutlined,
  ManOutlined,
  SearchOutlined,
} from "@ant-design/icons";
import { MapContainer, Marker, Polyline, Popup, TileLayer } from "react-leaflet";
import L from "leaflet";
import { BRAND } from "../theme";

interface LatLng {
  lat: number;
  lng: number;
}

interface RouteResult {
  ok: boolean;
  source: string;
  message?: string;
  mode: string;
  from?: string;
  to?: string;
  distance_km?: number | null;
  duration_min?: number | null;
  cost_yuan?: number | null;
  summary?: string | null;
  from_ll?: LatLng | null;
  to_ll?: LatLng | null;
  polyline?: [number, number][] | null;
}

const MODES = [
  { value: "transit", label: "公交/地铁", icon: <CompassOutlined /> },
  { value: "driving", label: "驾车", icon: <CarOutlined /> },
  { value: "walking", label: "步行", icon: <ManOutlined /> },
];

// 高德瓦片（无 key；与助手页地图同款）
const TILE_URL =
  "https://webrd0{s}.is.autonavi.com/appmaptile?lang=zh_cn&size=1&scale=1&style=8&x={x}&y={y}&z={z}";

// 起终点圆形标记（divIcon：bundler 下 Leaflet 默认图标资源会 404）
function makeEndIcon(kind: "起" | "终", color: string) {
  return L.divIcon({
    className: "",
    html: `<div style="background:${color};color:#fff;border-radius:9999px;width:22px;height:22px;display:flex;align-items:center;justify-content:center;font-size:11px;border:2px solid #fff;box-shadow:0 1px 3px rgba(0,0,0,.4)">${kind}</div>`,
    iconSize: [22, 22],
    iconAnchor: [11, 11],
  });
}

function RouteMap({
  result,
}: {
  result: RouteResult;
}) {
  if (!result.from_ll || !result.to_ll) return null;
  const points: [number, number][] = result.polyline?.length
    ? result.polyline
    : [[result.from_ll.lat, result.from_ll.lng], [result.to_ll.lat, result.to_ll.lng]];
  // 每次查询结果 remount（key 由父组件控制），bounds 直接初始化
  const bounds = L.latLngBounds(points).pad(0.25);
  return (
    <MapContainer bounds={bounds} className="h-72 w-full" scrollWheelZoom={false}>
      <TileLayer
        url={TILE_URL}
        subdomains={["1", "2", "3", "4"]}
        maxZoom={18}
        attribution="© 高德地图"
      />
      <Marker position={[result.from_ll.lat, result.from_ll.lng]} icon={makeEndIcon("起", "#16a34a")}>
        <Popup>
          <span className="text-xs">起点：{result.from}</span>
        </Popup>
      </Marker>
      <Marker position={[result.to_ll.lat, result.to_ll.lng]} icon={makeEndIcon("终", "#dc2626")}>
        <Popup>
          <span className="text-xs">终点：{result.to}</span>
        </Popup>
      </Marker>
      {result.polyline?.length ? (
        <Polyline positions={result.polyline} pathOptions={{ color: BRAND, weight: 4 }} />
      ) : (
        // 降级估算：无路线几何 → 起终点虚线直线（来源标注"仅供参考"）
        <Polyline
          positions={points}
          pathOptions={{ color: "#f59e0b", weight: 2, dashArray: "6 8" }}
        />
      )}
    </MapContainer>
  );
}

export default function TransportPlanner() {
  const [city, setCity] = useState("");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [mode, setMode] = useState("transit");
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<RouteResult | null>(null);

  const search = async () => {
    if (!from.trim() || !to.trim() || loading) return;
    setLoading(true);
    setResult(null);
    try {
      const params = new URLSearchParams({
        city: city.trim(),
        from: from.trim(),
        to: to.trim(),
        mode,
      });
      const resp = await fetch(`/api/route?${params}`);
      if (!resp.ok) throw new Error(`请求失败 (${resp.status})`);
      setResult(await resp.json());
    } catch {
      setResult({ ok: false, source: "error", mode, message: "查询失败，请稍后重试" });
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="mx-auto max-w-2xl p-4 md:p-6">
      <h2 className="mb-1 text-lg font-semibold text-slate-800">交通规划</h2>
      <p className="mb-4 text-sm text-slate-500">
        查询两个地点之间的交通方式、耗时与费用（数据来自高德地图）
      </p>

      <Card size="small">
        <div className="space-y-3">
          <div className="flex gap-2">
            <Input
              placeholder="城市（如：成都，公交查询必填）"
              value={city}
              onChange={(e) => setCity(e.target.value)}
              prefix={<EnvironmentOutlined className="text-slate-400" />}
              onPressEnter={search}
            />
          </div>
          <Input
            placeholder="起点（如：天府广场）"
            value={from}
            onChange={(e) => setFrom(e.target.value)}
            onPressEnter={search}
          />
          <Input
            placeholder="终点（如：宽窄巷子）"
            value={to}
            onChange={(e) => setTo(e.target.value)}
            onPressEnter={search}
          />
          <div className="flex flex-wrap items-center justify-between gap-2">
            <Radio.Group
              value={mode}
              onChange={(e) => setMode(e.target.value)}
              options={MODES.map((m) => ({
                value: m.value,
                label: (
                  <span>
                    {m.icon} {m.label}
                  </span>
                ),
              }))}
              optionType="button"
            />
            <Button
              type="primary"
              icon={<SearchOutlined />}
              loading={loading}
              onClick={search}
            >
              查询
            </Button>
          </div>
        </div>
      </Card>

      <div className="mt-4">
        {loading && (
          <div className="flex justify-center py-10">
            <Spin tip="正在查询路线…" />
          </div>
        )}
        {!loading && result && !result.ok && (
          <Alert type="warning" showIcon message={result.message} />
        )}
        {!loading && result?.ok && (
          <Card size="small">
            <div className="flex items-center gap-2 text-sm text-slate-500">
              <span>{result.from}</span>
              <span className="text-brand">→</span>
              <span>{result.to}</span>
              <span className="ml-auto">
                {MODES.find((m) => m.value === result?.mode)?.label}
              </span>
            </div>
            {result.source === "estimate" && (
              <Alert
                className="mt-3"
                type="info"
                showIcon
                message={result.message}
              />
            )}
            <div className="mt-4 flex flex-wrap gap-6">
              {result.duration_min != null && (
                <div>
                  <div className="text-2xl font-bold text-brand">
                    {result.duration_min}
                    <span className="ml-1 text-sm font-normal text-slate-500">
                      分钟
                    </span>
                  </div>
                  <div className="text-xs text-slate-500">预计耗时</div>
                </div>
              )}
              {result.distance_km != null && (
                <div>
                  <div className="text-2xl font-bold text-slate-800">
                    {result.distance_km}
                    <span className="ml-1 text-sm font-normal text-slate-500">
                      公里
                    </span>
                  </div>
                  <div className="text-xs text-slate-500">距离</div>
                </div>
              )}
              {result.cost_yuan != null && (
                <div>
                  <div className="text-2xl font-bold text-slate-800">
                    ¥{result.cost_yuan}
                  </div>
                  <div className="text-xs text-slate-500">费用（参考）</div>
                </div>
              )}
            </div>
            {result.summary && (
              <div className="mt-3 rounded-lg bg-brand/5 px-3 py-2 text-sm text-slate-700">
                {result.summary}
              </div>
            )}
          </Card>
        )}
        {!loading && result?.ok && result.from_ll && result.to_ll && (
          <Card size="small" className="mt-3 overflow-hidden" styles={{ body: { padding: 0 } }}>
            <RouteMap
              key={`${result.from}|${result.to}|${result.mode}|${result.duration_min}|${result.distance_km}`}
              result={result}
            />
          </Card>
        )}
      </div>
    </div>
  );
}
