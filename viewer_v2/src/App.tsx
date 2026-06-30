import { useEffect, useMemo, useState } from "react";
import type React from "react";
import { loadExamBundle, loadPatients, loadViewerData } from "./data";
import {
  activeBurden,
  countByStatus,
  enrichFindings,
  findEvidenceSpans,
  latestObservation,
  sideLabel,
  sortFindings,
  statusLabel,
  uniqueBy,
  warningMatchesFinding,
} from "./logic";
import type {
  EnrichedFinding,
  ExamBundle,
  Laterality,
  Observation,
  RegionConfig,
  Status,
  ViewerData,
  WarningRecord,
} from "./types";

type Selection = {
  regionId: string | null;
  regionSide: Laterality | null;
  regionLabel: string | null;
  clusterId: string | null;
  findingId: string | null;
  observationId: string | null;
};

type StatusFilters = Record<Status, boolean>;

const initialStatusFilters: StatusFilters = {
  current: true,
  always: true,
  resolved: true,
  never_present: false,
};

type DiagramCell = {
  regionId: string;
  side?: Laterality;
  label?: string;
  area: string;
  shapeClass: string;
};

const bodyCells: DiagramCell[] = [
  { regionId: "head", area: "head", shapeClass: "min-h-[92px] rounded-[48%]" },
  { regionId: "neck", area: "neck", shapeClass: "min-h-[46px] rounded-full" },
  {
    regionId: "upper_extremity",
    side: "right",
    label: "Right Upper Extremity",
    area: "rightUpper",
    shapeClass: "min-h-[190px] rounded-[28px]",
  },
  {
    regionId: "thorax",
    area: "thorax",
    shapeClass: "min-h-[180px] rounded-t-[48px] rounded-b-lg",
  },
  {
    regionId: "upper_extremity",
    side: "left",
    label: "Left Upper Extremity",
    area: "leftUpper",
    shapeClass: "min-h-[190px] rounded-[28px]",
  },
  { regionId: "breast", area: "breast", shapeClass: "min-h-[58px] rounded-[42%]" },
  { regionId: "abdomen", area: "abdomen", shapeClass: "min-h-[122px] rounded-[34px]" },
  {
    regionId: "lower_extremity",
    side: "right",
    label: "Right Lower Extremity",
    area: "rightLower",
    shapeClass: "min-h-[170px] rounded-[28px]",
  },
  { regionId: "pelvis", area: "pelvis", shapeClass: "min-h-[96px] rounded-b-[44px] rounded-t-lg" },
  {
    regionId: "lower_extremity",
    side: "left",
    label: "Left Lower Extremity",
    area: "leftLower",
    shapeClass: "min-h-[170px] rounded-[28px]",
  },
];

function getQuerySelection(): Selection {
  const params = new URLSearchParams(window.location.search);
  return {
    regionId: params.get("region"),
    regionSide: null,
    regionLabel: null,
    clusterId: params.get("cluster"),
    findingId: params.get("finding"),
    observationId: params.get("observation"),
  };
}

function emptySelection(): Selection {
  return {
    regionId: null,
    regionSide: null,
    regionLabel: null,
    clusterId: null,
    findingId: null,
    observationId: null,
  };
}

function setQueryState(patientId: string, selection: Selection): void {
  const params = new URLSearchParams();
  params.set("patient", patientId);
  if (selection.regionId) {
    params.set("region", selection.regionId);
  }
  if (selection.clusterId) {
    params.set("cluster", selection.clusterId);
  }
  if (selection.findingId) {
    params.set("finding", selection.findingId);
  }
  if (selection.observationId) {
    params.set("observation", selection.observationId);
  }
  window.history.replaceState(null, "", `${window.location.pathname}?${params.toString()}`);
}

function hasStatus(filters: StatusFilters, status: Status): boolean {
  return filters[status];
}

function statusTone(status: Status): string {
  switch (status) {
    case "current":
      return "bg-red-950 text-red-200 ring-red-700";
    case "always":
      return "bg-amber-950 text-amber-200 ring-amber-700";
    case "resolved":
      return "bg-slate-800 text-slate-300 ring-slate-600";
    case "never_present":
      return "bg-zinc-900 text-zinc-400 ring-zinc-700";
  }
}

function statusControlLabel(status: Status): string {
  switch (status) {
    case "always":
      return "Always";
    case "current":
      return "Current";
    case "resolved":
      return "Resolved";
    case "never_present":
      return "Never";
  }
}

function formatDate(value?: string): string {
  if (!value) {
    return "Unknown date";
  }
  return value;
}

function App() {
  const [patientId, setPatientId] = useState<string | null>(null);
  const [knownPatients, setKnownPatients] = useState<ViewerData["patients"]>([]);
  const [data, setData] = useState<ViewerData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selection, setSelection] = useState<Selection>(() => getQuerySelection());
  const [search, setSearch] = useState("");
  const [statusFilters, setStatusFilters] = useState<StatusFilters>(initialStatusFilters);
  const [examBundles, setExamBundles] = useState<Record<string, ExamBundle>>({});
  const [examLoading, setExamLoading] = useState(false);

  useEffect(() => {
    let cancelled = false;
    async function boot() {
      try {
        const patients = await loadPatients();
        if (cancelled) {
          return;
        }
        setKnownPatients(patients);
        const params = new URLSearchParams(window.location.search);
        const requestedPatient = params.get("patient");
        const firstPatient = patients[0]?.id;
        if (!firstPatient) {
          throw new Error("No generated patients are available.");
        }
        if (!requestedPatient) {
          setQueryState(firstPatient, getQuerySelection());
          setPatientId(firstPatient);
          return;
        }
        if (!patients.some((patient) => patient.id === requestedPatient)) {
          setError(`Unknown patient: ${requestedPatient}`);
          setPatientId(null);
          return;
        }
        setPatientId(requestedPatient);
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
      }
    }
    void boot();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!patientId) {
      return;
    }
    const activePatientId = patientId;
    let cancelled = false;
    async function load() {
      try {
        setError(null);
        const loaded = await loadViewerData(activePatientId);
        if (cancelled) {
          return;
        }
        setData(loaded);
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : String(err));
        }
      }
    }
    void load();
    return () => {
      cancelled = true;
    };
  }, [patientId]);

  const findings = useMemo(() => {
    if (!data) {
      return [];
    }
    return enrichFindings({
      findings: data.ipl.findings,
      statusByFindingId: data.ipl.viewerMetadata.statusByFindingId,
      anatomyClusters: data.anatomyClusters,
      anatomyIndex: data.anatomyIndex,
      definitions: data.definitions,
    });
  }, [data]);

  useEffect(() => {
    if (!data || findings.length === 0 || !patientId) {
      return;
    }

    const knownRegionIds = new Set(data.anatomyClusters.regions.map((region) => region.id));
    const knownClusterIds = new Set(data.anatomyClusters.clusters.map((cluster) => cluster.id));
    const knownFindingIds = new Set(findings.map((finding) => finding.id));
    let next = selection;

    if (next.regionId && !knownRegionIds.has(next.regionId)) {
      next = emptySelection();
    }
    if (next.clusterId && !knownClusterIds.has(next.clusterId)) {
      next = { ...next, clusterId: null, findingId: null, observationId: null };
    }
    if (next.findingId && !knownFindingIds.has(next.findingId)) {
      next = { ...next, findingId: null, observationId: null };
    }
    if (next !== selection) {
      setSelection(next);
    }
    setQueryState(patientId, next);
  }, [data, findings, patientId, selection]);

  const selectedFinding = findings.find((finding) => finding.id === selection.findingId) ?? null;
  const selectedObservation =
    selectedFinding?.finding.observations.find(
      (observation) => observation.observation_id === selection.observationId,
    ) ?? null;

  useEffect(() => {
    if (!patientId || !selectedObservation) {
      return;
    }
    const activePatientId = patientId;
    const activeObservation = selectedObservation;
    if (examBundles[activeObservation.report_id]) {
      return;
    }
    let cancelled = false;
    async function loadExam() {
      try {
        setExamLoading(true);
        const bundle = await loadExamBundle(activePatientId, activeObservation.report_id);
        if (!cancelled) {
          setExamBundles((current) => ({
            ...current,
            [activeObservation.report_id]: bundle,
          }));
        }
      } finally {
        if (!cancelled) {
          setExamLoading(false);
        }
      }
    }
    void loadExam();
    return () => {
      cancelled = true;
    };
  }, [examBundles, patientId, selectedObservation]);

  const filteredFindings = useMemo(() => {
    const query = search.trim().toLowerCase();
    return findings
      .filter((finding) => hasStatus(statusFilters, finding.status))
      .filter((finding) => {
        if (!query) {
          return true;
        }
        return [
          finding.display,
          finding.compactDisplay,
          finding.code,
          finding.locationDisplay,
          finding.regionLabel,
          finding.clusterLabel,
          ...finding.finding.observations.map((observation) => observation.reportText || ""),
        ]
          .join(" ")
          .toLowerCase()
          .includes(query);
      })
      .sort(sortFindings);
  }, [findings, search, statusFilters]);

  const visibleFindings = filteredFindings.filter((finding) => {
    if (selection.findingId) {
      return finding.id === selection.findingId;
    }
    if (selection.clusterId) {
      return finding.clusterId === selection.clusterId;
    }
    if (selection.regionId) {
      return (
        finding.regionId === selection.regionId &&
        (!selection.regionSide || finding.laterality === selection.regionSide)
      );
    }
    return true;
  });
  function choosePatient(nextPatientId: string) {
    setPatientId(nextPatientId);
    setSelection(emptySelection());
    setData(null);
    setExamBundles({});
    setQueryState(nextPatientId, emptySelection());
  }

  function selectRegion(
    regionId: string,
    regionSide: Laterality | null = null,
    regionLabel: string | null = null,
  ) {
    const next = {
      regionId,
      regionSide,
      regionLabel,
      clusterId: null,
      findingId: null,
      observationId: null,
    };
    setSelection(next);
    if (patientId) {
      setQueryState(patientId, next);
    }
  }

  function selectCluster(regionId: string, clusterId: string) {
    const next = {
      regionId,
      regionSide: selection.regionId === regionId ? selection.regionSide : null,
      regionLabel: selection.regionId === regionId ? selection.regionLabel : null,
      clusterId,
      findingId: null,
      observationId: null,
    };
    setSelection(next);
    if (patientId) {
      setQueryState(patientId, next);
    }
  }

  function selectFinding(finding: EnrichedFinding) {
    const next = {
      regionId: finding.regionId,
      regionSide: selection.regionId === finding.regionId ? selection.regionSide : null,
      regionLabel: selection.regionId === finding.regionId ? selection.regionLabel : null,
      clusterId: finding.clusterId,
      findingId: finding.id,
      observationId: null,
    };
    setSelection(next);
    if (patientId) {
      setQueryState(patientId, next);
    }
  }

  function selectObservation(observationId: string | null) {
    const next = { ...selection, observationId };
    setSelection(next);
    if (patientId) {
      setQueryState(patientId, next);
    }
  }

  if (error) {
    return (
      <main className="min-h-screen bg-slate-100 p-6 text-slate-900">
        <div className="mx-auto max-w-3xl rounded border border-red-200 bg-white p-5">
          <h1 className="text-xl font-semibold">Unable to load viewer data</h1>
          <p className="mt-2 text-sm text-red-700">{error}</p>
          {knownPatients[0] ? (
            <button
              className="mt-4 rounded bg-slate-900 px-3 py-2 text-sm font-medium text-white"
              onClick={() => choosePatient(knownPatients[0].id)}
            >
              Open {knownPatients[0].displayName}
            </button>
          ) : null}
        </div>
      </main>
    );
  }

  if (!data) {
    return (
      <main className="grid min-h-screen place-items-center bg-slate-100 text-slate-700">
        <div className="rounded border border-slate-200 bg-white px-5 py-4 text-sm">
          Loading anatomy viewer...
        </div>
      </main>
    );
  }

  return (
    <main className="min-h-screen bg-[#f4f6f8] text-slate-900">
      <TopBar
        data={data}
        patients={knownPatients}
        patientId={patientId ?? data.patient.id}
        onPatientChange={choosePatient}
        search={search}
        onSearch={setSearch}
        statusFilters={statusFilters}
        onStatusFilters={setStatusFilters}
      />
      <div className="grid min-h-[calc(100vh-84px)] grid-cols-1 items-start gap-3 p-3 lg:grid-cols-[minmax(520px,0.95fr)_minmax(420px,1.05fr)]">
        <section className="order-1 min-h-[520px] rounded border border-slate-200 bg-white p-3 shadow-sm">
          <Diagram
            regions={data.anatomyClusters.regions}
            findings={filteredFindings}
            allFindings={findings}
            selection={selection}
            onRegion={selectRegion}
            onFinding={selectFinding}
          />
        </section>
        <section className="order-2 rounded border border-slate-200 bg-white shadow-sm">
          <DetailPane
            data={data}
            findings={visibleFindings}
            allFilteredFindings={filteredFindings}
            allFindings={findings}
            selection={selection}
            selectedFinding={selectedFinding}
            selectedObservation={selectedObservation}
            examBundle={
              selectedObservation ? examBundles[selectedObservation.report_id] : undefined
            }
            examLoading={examLoading}
            onClear={() =>
              setSelection({
                regionId: null,
                regionSide: null,
                regionLabel: null,
                clusterId: null,
                findingId: null,
                observationId: null,
              })
            }
            onRegion={selectRegion}
            onCluster={selectCluster}
            onFinding={selectFinding}
            onObservation={selectObservation}
          />
        </section>
      </div>
    </main>
  );
}

function TopBar(props: {
  data: ViewerData;
  patients: ViewerData["patients"];
  patientId: string;
  onPatientChange: (patientId: string) => void;
  search: string;
  onSearch: (value: string) => void;
  statusFilters: StatusFilters;
  onStatusFilters: (filters: StatusFilters) => void;
}) {
  return (
    <header className="border-b border-slate-200 bg-white/95 px-4 py-3 shadow-sm backdrop-blur">
      <div className="flex flex-col gap-3 xl:flex-row xl:items-center xl:justify-between">
        <div className="flex flex-wrap items-center gap-3">
          <div>
            <div className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">
              Anatomy IPL
            </div>
            <div className="text-lg font-semibold text-slate-950">
              {props.data.patient.displayName}
            </div>
          </div>
          <div className="text-sm text-slate-600">
            MRN {props.data.patient.mrn}
            {props.data.patient.dob ? ` | DOB ${props.data.patient.dob}` : ""}
          </div>
          {props.patients.length > 1 ? (
            <select
              className="rounded border border-slate-300 bg-white px-2 py-1 text-sm"
              value={props.patientId}
              onChange={(event) => props.onPatientChange(event.target.value)}
            >
              {props.patients.map((patient) => (
                <option key={patient.id} value={patient.id}>
                  {patient.displayName}
                </option>
              ))}
            </select>
          ) : null}
        </div>
        <div className="flex flex-col gap-2 xl:items-end">
          <div className="flex items-center gap-2">
            <input
              className="min-w-0 flex-1 rounded border border-slate-300 bg-white px-3 py-2 text-sm outline-none ring-cyan-500 focus:ring-2 xl:w-80 xl:flex-none"
              placeholder="Search findings, locations, evidence"
              value={props.search}
              onChange={(event) => props.onSearch(event.target.value)}
            />
            <button
              className="rounded border border-slate-300 px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50"
              onClick={() => props.onSearch("")}
            >
              Clear
            </button>
          </div>
          <div className="flex flex-wrap gap-1.5 text-xs xl:justify-end">
            {(["current", "always", "resolved", "never_present"] as Status[]).map((status) => (
              <button
                key={status}
                className={`rounded border px-2 py-1 font-medium ${
                  props.statusFilters[status]
                    ? "border-cyan-700 bg-cyan-50 text-cyan-900"
                    : "border-slate-300 bg-white text-slate-500"
                }`}
                onClick={() =>
                  props.onStatusFilters({
                    ...props.statusFilters,
                    [status]: !props.statusFilters[status],
                  })
                }
              >
                {statusControlLabel(status)}
              </button>
            ))}
          </div>
        </div>
      </div>
    </header>
  );
}

function Diagram(props: {
  regions: RegionConfig[];
  findings: EnrichedFinding[];
  allFindings: EnrichedFinding[];
  selection: Selection;
  onRegion: (regionId: string, regionSide?: Laterality | null, regionLabel?: string | null) => void;
  onFinding: (finding: EnrichedFinding) => void;
}) {
  const regionMap = new Map(props.regions.map((region) => [region.id, region]));
  const maxBurden = Math.max(
    1,
    ...props.regions.map((region) =>
      activeBurden(props.findings.filter((finding) => finding.regionId === region.id)),
    ),
  );
  const unlocalizedFindings = props.findings.filter(
    (finding) => finding.regionId === "unlocalized",
  );
  const allUnlocalizedFindings = props.allFindings.filter(
    (finding) => finding.regionId === "unlocalized",
  );
  const unlocalizedCounts = countByStatus(unlocalizedFindings);
  const showUnlocalizedTray =
    unlocalizedCounts.current +
      unlocalizedCounts.always +
      unlocalizedCounts.resolved +
      unlocalizedCounts.never_present >
    0;

  return (
    <div className="flex h-full flex-col gap-3">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h1 className="text-base font-semibold text-slate-950">
            Anatomy dashboard
          </h1>
        </div>
        <div className="text-right text-xs text-slate-500">
          <div>Active burden = current + always present</div>
          <div>Empty anatomy stays visible</div>
        </div>
      </div>
      <DiagramLegend />
      <div
        className="body-map-grid grid items-center gap-2"
      >
        {bodyCells.map((cell) => {
          const region = regionMap.get(cell.regionId);
          if (!region) {
            return null;
          }
          const regionFindings = props.findings.filter(
            (finding) =>
              finding.regionId === region.id && (!cell.side || finding.laterality === cell.side),
          );
          const allRegionFindings = props.allFindings.filter(
            (finding) =>
              finding.regionId === region.id && (!cell.side || finding.laterality === cell.side),
          );
          return (
            <BodyZone
              key={`${cell.regionId}:${cell.side ?? "all"}`}
              cell={cell}
              region={region}
              findings={regionFindings}
              allFindings={allRegionFindings}
              selected={
                props.selection.regionId === region.id &&
                (cell.side ? props.selection.regionSide === cell.side : !props.selection.regionSide)
              }
              maxBurden={maxBurden}
              onClick={() => props.onRegion(region.id, cell.side ?? null, cell.label ?? null)}
              onFinding={props.onFinding}
            />
          );
        })}
      </div>
      {showUnlocalizedTray ? (
        <UnlocalizedTray
          findings={unlocalizedFindings}
          allFindings={allUnlocalizedFindings}
          selected={props.selection.regionId === "unlocalized"}
          maxBurden={maxBurden}
          onClick={() => props.onRegion("unlocalized")}
          onFinding={props.onFinding}
        />
      ) : null}
    </div>
  );
}

function DiagramLegend() {
  return (
    <div className="grid gap-2 rounded border border-slate-200 bg-slate-50 p-2 text-[11px] text-slate-600 sm:grid-cols-[1fr_auto_auto] sm:items-center">
      <div className="flex flex-wrap items-center gap-1.5">
        <span className="font-semibold text-slate-500">Burden</span>
        <span className="h-3 w-7 rounded border border-slate-200 bg-[#101820]" />
        <span className="h-3 w-7 rounded border border-slate-200 bg-[#152323]" />
        <span className="h-3 w-7 rounded border border-slate-200 bg-[#1b2f36]" />
        <span className="h-3 w-7 rounded border border-slate-200 bg-[#263e4d]" />
        <span className="text-slate-500">low to high active findings</span>
      </div>
      <div className="flex items-center gap-1.5">
        <span className="h-3 w-7 rounded border-2 border-slate-400 bg-transparent" />
        <span>selected</span>
      </div>
      <div className="flex items-center gap-1.5">
        <span className="rounded-full bg-slate-800 px-2 py-0.5 text-[10px] font-semibold text-slate-300 ring-1 ring-slate-600">
          resolved
        </span>
        <span>secondary</span>
      </div>
    </div>
  );
}

function BodyZone(props: {
  cell: DiagramCell;
  region: RegionConfig;
  findings: EnrichedFinding[];
  allFindings: EnrichedFinding[];
  selected: boolean;
  maxBurden: number;
  onClick: () => void;
  onFinding: (finding: EnrichedFinding) => void;
}) {
  return (
    <AnatomyZone
      label={props.cell.label || props.region.label}
      side={props.cell.side}
      area={props.cell.area}
      shapeClass={props.cell.shapeClass}
      findings={props.findings}
      allFindings={props.allFindings}
      selected={props.selected}
      maxBurden={props.maxBurden}
      testId={`region-${props.region.id}${props.cell.side ? `-${props.cell.side}` : ""}`}
      onClick={props.onClick}
      onFinding={props.onFinding}
    />
  );
}

function UnlocalizedTray(props: {
  findings: EnrichedFinding[];
  allFindings: EnrichedFinding[];
  selected: boolean;
  maxBurden: number;
  onClick: () => void;
  onFinding: (finding: EnrichedFinding) => void;
}) {
  return (
    <AnatomyZone
      label="Unlocalized"
      area="unlocalized"
      shapeClass="min-h-[72px] rounded-full"
      findings={props.findings}
      allFindings={props.allFindings}
      selected={props.selected}
      maxBurden={props.maxBurden}
      testId="region-unlocalized"
      onClick={props.onClick}
      onFinding={props.onFinding}
      offFigure
    />
  );
}

function AnatomyZone(props: {
  label: string;
  side?: Laterality;
  area: string;
  shapeClass: string;
  findings: EnrichedFinding[];
  allFindings: EnrichedFinding[];
  selected: boolean;
  maxBurden: number;
  testId: string;
  onClick: () => void;
  onFinding: (finding: EnrichedFinding) => void;
  offFigure?: boolean;
}) {
  const counts = countByStatus(props.findings);
  const active = counts.current + counts.always;
  const resolved = counts.resolved;
  const hasAny = props.allFindings.length > 0;
  const ratio = active / Math.max(props.maxBurden, 1);
  const background = heatmapColor(active, ratio, hasAny);
  const borderColor = props.selected ? "#64748b" : hasAny ? "#475569" : "#263241";
  const textColor = "#e5edf6";

  return (
    <div
      role="button"
      tabIndex={0}
      className={`group border p-3 text-left outline-none transition hover:border-slate-400 hover:shadow-sm focus:ring-1 focus:ring-slate-400 ${props.shapeClass} ${
        props.selected ? "ring-1 ring-slate-400" : ""
      } ${props.offFigure ? "mt-3 border-dashed" : ""}`}
      style={{
        gridArea: props.offFigure ? undefined : props.area,
        background,
        borderColor,
        color: textColor,
      }}
      onClick={props.onClick}
      onKeyDown={(event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          props.onClick();
        }
      }}
      data-testid={props.testId}
      aria-label={`${props.label}, ${active} active findings, ${resolved} resolved findings`}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="text-sm font-semibold leading-tight text-slate-950">{props.label}</div>
        {resolved ? (
          <button
            className="resolved-count-button rounded-full bg-white/80 px-2 py-0.5 text-[11px] font-semibold text-slate-600 ring-1 ring-slate-200 hover:bg-slate-50"
            onClick={(event) => {
              event.stopPropagation();
              props.onClick();
            }}
            title={`${resolved} resolved findings`}
          >
            {resolved} resolved
          </button>
        ) : null}
      </div>
      <ActiveFindingChips
        findings={props.findings}
        onFinding={props.onFinding}
      />
    </div>
  );
}

function ActiveFindingChips(props: {
  findings: EnrichedFinding[];
  onFinding: (finding: EnrichedFinding) => void;
}) {
  const [currentExpanded, setCurrentExpanded] = useState(false);
  const [alwaysExpanded, setAlwaysExpanded] = useState(false);
  const currentFindings = props.findings
    .filter((finding) => finding.status === "current")
    .sort(sortFindings);
  const alwaysFindings = props.findings
    .filter((finding) => finding.status === "always")
    .sort(sortFindings);
  const initialLimit = Math.min(currentFindings.length, 8);
  const visibleCurrent = currentExpanded
    ? currentFindings
    : currentFindings.slice(0, initialLimit);
  const hiddenCurrent = currentFindings.slice(initialLimit);

  if (currentFindings.length === 0 && alwaysFindings.length === 0) {
    return <div className="mt-3 text-[11px] font-medium text-slate-500">No active findings</div>;
  }

  return (
    <div className="mt-3 flex flex-wrap gap-1.5">
      {visibleCurrent.map((finding) => (
        <button
          key={finding.id}
          className={`active-finding-chip active-finding-chip-${finding.status} max-w-full rounded bg-white/90 px-2 py-1 text-left text-[11px] font-semibold leading-tight text-slate-800 ring-1 ring-slate-200 hover:bg-cyan-50 hover:ring-cyan-300 sm:w-auto`}
          title={`${statusLabel(finding.status)} | ${finding.display} | ${finding.locationDisplay}`}
          aria-label={`${statusLabel(finding.status)}: ${finding.display}`}
          onClick={(event) => {
            event.stopPropagation();
            props.onFinding(finding);
          }}
        >
          {finding.compactDisplay}
        </button>
      ))}
      {hiddenCurrent.length && !currentExpanded ? (
        <button
          className="overflow-findings-button max-w-full rounded border border-dashed border-slate-300 bg-transparent px-2 py-1 text-left text-[11px] font-semibold leading-tight text-slate-500 hover:bg-cyan-50 hover:ring-1 hover:ring-cyan-300"
          title={hiddenCurrent
            .map((finding) => `${finding.display} | ${finding.locationDisplay}`)
            .join("\n")}
          aria-expanded={false}
          onClick={(event) => {
            event.stopPropagation();
            setCurrentExpanded(true);
          }}
        >
          {hiddenCurrent.length} more active
        </button>
      ) : null}
      {hiddenCurrent.length && currentExpanded ? (
        <button
          className="overflow-findings-button max-w-full rounded border border-dashed border-slate-300 bg-transparent px-2 py-1 text-left text-[11px] font-semibold leading-tight text-slate-500 hover:bg-cyan-50 hover:ring-1 hover:ring-cyan-300"
          aria-expanded
          onClick={(event) => {
            event.stopPropagation();
            setCurrentExpanded(false);
          }}
        >
          fewer active
        </button>
      ) : null}
      {alwaysFindings.length && !alwaysExpanded ? (
        <button
          className="overflow-findings-button overflow-findings-button-always max-w-full rounded border border-dashed border-slate-300 bg-transparent px-2 py-1 text-left text-[11px] font-semibold leading-tight text-slate-500 hover:bg-cyan-50 hover:ring-1 hover:ring-cyan-300"
          title={alwaysFindings
            .map((finding) => `${finding.display} | ${finding.locationDisplay}`)
            .join("\n")}
          aria-expanded={false}
          onClick={(event) => {
            event.stopPropagation();
            setAlwaysExpanded(true);
          }}
        >
          {alwaysFindings.length} always
        </button>
      ) : null}
      {alwaysExpanded
        ? alwaysFindings.map((finding) => (
            <button
              key={finding.id}
              className={`active-finding-chip active-finding-chip-${finding.status} max-w-full rounded bg-white/90 px-2 py-1 text-left text-[11px] font-semibold leading-tight text-slate-800 ring-1 ring-slate-200 hover:bg-cyan-50 hover:ring-cyan-300 sm:w-auto`}
              title={`${statusLabel(finding.status)} | ${finding.display} | ${finding.locationDisplay}`}
              aria-label={`${statusLabel(finding.status)}: ${finding.display}`}
              onClick={(event) => {
                event.stopPropagation();
                props.onFinding(finding);
              }}
            >
              {finding.compactDisplay}
            </button>
          ))
        : null}
      {alwaysFindings.length && alwaysExpanded ? (
        <button
          className="overflow-findings-button overflow-findings-button-always max-w-full rounded border border-dashed border-slate-300 bg-transparent px-2 py-1 text-left text-[11px] font-semibold leading-tight text-slate-500 hover:bg-cyan-50 hover:ring-1 hover:ring-cyan-300"
          aria-expanded
          onClick={(event) => {
            event.stopPropagation();
            setAlwaysExpanded(false);
          }}
        >
          hide always
        </button>
      ) : null}
    </div>
  );
}

function heatmapColor(active: number, ratio: number, hasAny: boolean): string {
  if (!hasAny) {
    return "#101820";
  }
  if (active === 0) {
    return "#17212b";
  }
  if (ratio < 0.2) {
    return "#152323";
  }
  if (ratio < 0.45) {
    return "#1b2f36";
  }
  if (ratio < 0.7) {
    return "#223847";
  }
  return "#263e4d";
}

function DetailPane(props: {
  data: ViewerData;
  findings: EnrichedFinding[];
  allFilteredFindings: EnrichedFinding[];
  allFindings: EnrichedFinding[];
  selection: Selection;
  selectedFinding: EnrichedFinding | null;
  selectedObservation: Observation | null;
  examBundle?: ExamBundle;
  examLoading: boolean;
  onClear: () => void;
  onRegion: (
    regionId: string,
    regionSide?: Laterality | null,
    regionLabel?: string | null,
  ) => void;
  onCluster: (regionId: string, clusterId: string) => void;
  onFinding: (finding: EnrichedFinding) => void;
  onObservation: (observationId: string | null) => void;
}) {
  if (props.selectedFinding) {
    return (
      <FindingDetail
        data={props.data}
        finding={props.selectedFinding}
        selectedObservation={props.selectedObservation}
        examBundle={props.examBundle}
        examLoading={props.examLoading}
        warnings={props.data.manifest.warnings.filter((warning) =>
          warningMatchesFinding(
            warning,
            props.selectedFinding?.id ?? "",
            props.selectedObservation?.observation_id,
          ),
        )}
        onBack={() =>
          props.onCluster(props.selectedFinding!.regionId, props.selectedFinding!.clusterId)
        }
        onObservation={props.onObservation}
      />
    );
  }

  if (props.selection.clusterId) {
    return (
      <ClusterDetail
        findings={props.findings}
        clusterId={props.selection.clusterId}
        onBack={() => props.selection.regionId && props.onRegion(props.selection.regionId)}
        onFinding={props.onFinding}
      />
    );
  }

  if (props.selection.regionId) {
    return (
      <RegionDetail
        regionId={props.selection.regionId}
        regionLabel={props.selection.regionLabel}
        findings={props.findings}
        allFindings={props.allFilteredFindings}
        clusters={props.data.anatomyClusters.clusters}
        onClear={props.onClear}
        onCluster={props.onCluster}
        onFinding={props.onFinding}
      />
    );
  }

  return (
    <PatientSummaryDetail
      data={props.data}
      findings={props.allFilteredFindings}
      allFindings={props.allFindings}
      onRegion={props.onRegion}
      onFinding={props.onFinding}
    />
  );
}

function PatientSummaryDetail(props: {
  data: ViewerData;
  findings: EnrichedFinding[];
  allFindings: EnrichedFinding[];
  onRegion: (
    regionId: string,
    regionSide?: Laterality | null,
    regionLabel?: string | null,
  ) => void;
  onFinding: (finding: EnrichedFinding) => void;
}) {
  const counts = countByStatus(props.findings);
  const regionMap = new Map(props.data.anatomyClusters.regions.map((region) => [region.id, region]));
  const regionRows = bodyCells
    .map((cell) => {
      const region = regionMap.get(cell.regionId);
      if (!region) {
        return null;
      }
      const regionFindings = props.findings.filter(
        (finding) =>
          finding.regionId === region.id && (!cell.side || finding.laterality === cell.side),
      );
      return {
        regionId: region.id,
        regionSide: cell.side ?? null,
        label: cell.label || region.label,
        active: activeBurden(regionFindings),
        resolved: regionFindings.filter((finding) => finding.status === "resolved").length,
        total: regionFindings.length,
      };
    })
    .filter((row): row is NonNullable<typeof row> => row !== null)
    .filter((row) => row.total > 0)
    .sort((a, b) => b.active - a.active || b.total - a.total);
  const recentPositive = props.findings
    .filter((finding) => latestObservation(finding)?.presence === "present")
    .sort((a, b) =>
      (latestObservation(b)?.exam_date || "").localeCompare(latestObservation(a)?.exam_date || ""),
    )
    .slice(0, 8);
  const unlocalized = props.allFindings.filter((finding) => finding.regionId === "unlocalized");

  return (
    <div className="space-y-4 p-4">
      <DetailHeader
        title="Whole-patient anatomy summary"
        subtitle="Findings are grouped by IPL problem row and displayed through anatomy."
      />
      <div className="grid grid-cols-2 gap-2 md:grid-cols-4">
        <Metric label="Active" value={counts.current + counts.always} />
        <Metric label="Resolved" value={counts.resolved} />
        <Metric label="Never present" value={counts.never_present} />
        <Metric label="Warnings" value={props.data.manifest.counts.warnings ?? 0} />
      </div>
      <section>
        <h2 className="mb-2 text-sm font-semibold text-slate-950">Highest-burden anatomy</h2>
        <div className="grid gap-2">
          {regionRows.map((row) => (
            <button
              key={`${row.regionId}:${row.regionSide ?? "all"}`}
              className="flex items-center justify-between rounded border border-slate-200 bg-slate-50 px-3 py-2 text-left hover:border-cyan-500"
              onClick={() => props.onRegion(row.regionId, row.regionSide, row.label)}
            >
              <span className="font-medium text-slate-900">{row.label}</span>
              <span className="text-sm text-slate-600">
                {row.active} active / {row.resolved} resolved
              </span>
            </button>
          ))}
        </div>
      </section>
      <section>
        <h2 className="mb-2 text-sm font-semibold text-slate-950">Recent positive observations</h2>
        <div className="divide-y divide-slate-200 rounded border border-slate-200">
          {recentPositive.map((finding) => {
            const latest = latestObservation(finding);
            return (
              <button
                key={finding.id}
                className="block w-full px-3 py-2 text-left hover:bg-cyan-50"
                onClick={() => props.onFinding(finding)}
              >
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <div className="font-medium text-slate-950" title={finding.display}>
                      {finding.compactDisplay}
                    </div>
                    <div className="text-xs text-slate-600">
                      {finding.locationDisplay} | {finding.clusterLabel}
                    </div>
                  </div>
                  <span className="shrink-0 text-xs text-slate-500">
                    {formatDate(latest?.exam_date)}
                  </span>
                </div>
              </button>
            );
          })}
        </div>
      </section>
      {unlocalized.length ? (
        <section className="rounded border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900">
          {unlocalized.length} findings do not have a specific anatomy location.
        </section>
      ) : null}
    </div>
  );
}

function RegionDetail(props: {
  regionId: string;
  regionLabel: string | null;
  findings: EnrichedFinding[];
  allFindings: EnrichedFinding[];
  clusters: ViewerData["anatomyClusters"]["clusters"];
  onClear: () => void;
  onCluster: (regionId: string, clusterId: string) => void;
  onFinding: (finding: EnrichedFinding) => void;
}) {
  const regionLabel = props.regionLabel || props.findings[0]?.regionLabel || props.regionId;
  const clusters = uniqueBy(props.findings, (finding) => finding.clusterId).sort((a, b) =>
    a.clusterLabel.localeCompare(b.clusterLabel),
  );
  const counts = countByStatus(props.findings);

  return (
    <div className="space-y-4 p-4">
      <DetailHeader
        title={regionLabel}
        subtitle={`${counts.current + counts.always} active, ${counts.resolved} resolved`}
        onBack={props.onClear}
        backLabel="All anatomy"
      />
      <section>
        <h2 className="mb-2 text-sm font-semibold text-slate-950">Sub-regions</h2>
        <div className="space-y-3">
          {clusters.map((clusterFinding) => {
            const clusterFindings = props.findings.filter(
              (finding) => finding.clusterId === clusterFinding.clusterId,
            );
            const clusterCounts = countByStatus(clusterFindings);
            return (
              <div
                key={clusterFinding.clusterId}
                className="rounded border border-slate-200 bg-slate-50 p-3"
                data-testid={`cluster-${clusterFinding.clusterId}`}
              >
                <div className="flex items-center justify-between gap-3">
                  <button
                    className="text-left font-medium text-slate-950 hover:text-cyan-900"
                    onClick={() => props.onCluster(props.regionId, clusterFinding.clusterId)}
                  >
                    {clusterFinding.clusterLabel}
                  </button>
                  <div className="shrink-0 text-sm text-slate-600">
                    {clusterCounts.current + clusterCounts.always} active /{" "}
                    {clusterCounts.resolved} resolved
                  </div>
                </div>
                <div className="mt-3">
                  <FindingList findings={clusterFindings} onFinding={props.onFinding} />
                </div>
              </div>
            );
          })}
        </div>
      </section>
    </div>
  );
}

function ClusterDetail(props: {
  findings: EnrichedFinding[];
  clusterId: string;
  onBack: () => void;
  onFinding: (finding: EnrichedFinding) => void;
}) {
  const clusterLabel = props.findings[0]?.clusterLabel || props.clusterId;
  const locations = uniqueBy(props.findings, (finding) => finding.locationDisplay).sort((a, b) =>
    a.locationDisplay.localeCompare(b.locationDisplay),
  );

  return (
    <div className="space-y-4 p-4">
      <DetailHeader
        title={clusterLabel}
        subtitle={`${locations.length} exact locations represented`}
        onBack={props.onBack}
        backLabel="Region"
      />
      {locations.map((location) => {
        const findings = props.findings.filter(
          (finding) => finding.locationDisplay === location.locationDisplay,
        );
        return (
          <section key={location.locationDisplay}>
            <h2 className="mb-2 text-sm font-semibold text-slate-950">
              {location.locationDisplay}
            </h2>
            <FindingList findings={findings} onFinding={props.onFinding} />
          </section>
        );
      })}
    </div>
  );
}

function FindingDetail(props: {
  data: ViewerData;
  finding: EnrichedFinding;
  selectedObservation: Observation | null;
  examBundle?: ExamBundle;
  examLoading: boolean;
  warnings: WarningRecord[];
  onBack: () => void;
  onObservation: (observationId: string | null) => void;
}) {
  const sortedObservations = [...props.finding.finding.observations].sort((a, b) =>
    (b.exam_date || "").localeCompare(a.exam_date || ""),
  );

  return (
    <div className="space-y-4 p-4">
      <DetailHeader
        title={props.finding.display}
        subtitle={props.finding.locationDisplay}
        onBack={props.onBack}
        backLabel="Sub-region"
      />
      <div className="flex flex-wrap gap-2">
        <StatusBadge status={props.finding.status} />
        <span className="rounded bg-slate-100 px-2 py-1 text-xs text-slate-700">
          {props.finding.code}
        </span>
        <span className="rounded bg-slate-100 px-2 py-1 text-xs text-slate-700">
          {sideLabel(props.finding.laterality)}
        </span>
      </div>
      <section>
        <h2 className="mb-2 text-sm font-semibold text-slate-950">Timeline</h2>
        <div className="space-y-2">
          {sortedObservations.map((observation) => (
            <button
              key={observation.observation_id}
              className={`block w-full rounded border p-3 text-left ${
                props.selectedObservation?.observation_id === observation.observation_id
                  ? "border-cyan-700 bg-cyan-50"
                  : "border-slate-200 bg-slate-50 hover:border-cyan-500"
              }`}
              onClick={() => props.onObservation(observation.observation_id)}
              data-testid={`observation-${observation.observation_id}`}
            >
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="font-medium text-slate-950">
                  {formatDate(observation.exam_date)}
                </div>
                <span
                  className={`rounded px-2 py-1 text-xs font-semibold ${
                    observation.presence === "present"
                      ? "bg-red-50 text-red-800"
                      : "bg-slate-100 text-slate-700"
                  }`}
                >
                  {observation.presence}
                </span>
              </div>
              <div className="mt-1 text-sm text-slate-600">
                {observation.exam_type_display}
              </div>
              {observation.reportText ? (
                <div className="mt-2 text-sm text-slate-700">{observation.reportText}</div>
              ) : null}
            </button>
          ))}
        </div>
      </section>
      <MetadataSections finding={props.finding} />
      {props.warnings.length ? <WarningList warnings={props.warnings} /> : null}
      {props.selectedObservation ? (
        <ObservationDrilldown
          finding={props.finding}
          observation={props.selectedObservation}
          bundle={props.examBundle}
          loading={props.examLoading}
        />
      ) : null}
    </div>
  );
}

function ObservationDrilldown(props: {
  finding: EnrichedFinding;
  observation: Observation;
  bundle?: ExamBundle;
  loading: boolean;
}) {
  const eflFinding = props.bundle?.efl.findings?.find(
    (finding) => finding.observationId === props.observation.observation_id,
  );
  const spans = props.bundle
    ? findEvidenceSpans(props.bundle.report, props.observation.reportText)
    : [];

  return (
    <section className="space-y-3 rounded border border-slate-200 bg-slate-50 p-3">
      <h2 className="text-sm font-semibold text-slate-950">Exam and report drilldown</h2>
      {props.loading && !props.bundle ? (
        <div className="text-sm text-slate-600">Loading exam bundle...</div>
      ) : null}
      {props.bundle ? (
        <>
          <div className="grid gap-2 text-sm sm:grid-cols-2">
            <Info label="Exam" value={props.observation.exam_type_display} />
            <Info label="Date" value={formatDate(props.observation.exam_date)} />
            <Info label="Report ID" value={props.observation.report_id} />
            <Info label="EFL findings" value={`${props.bundle.efl.findings?.length ?? 0}`} />
          </div>
          {eflFinding ? (
            <div className="rounded border border-slate-200 bg-white p-3 text-sm">
              <div className="font-medium text-slate-950">EFL observation</div>
              <div className="mt-1 text-slate-700">{eflFinding.findingDescription}</div>
              <div className="mt-1 text-xs text-slate-500">
                {eflFinding.anatomicLocation?.locationDisplay || props.finding.locationDisplay}
              </div>
            </div>
          ) : (
            <div className="rounded border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900">
              Matching EFL observation was not found in the generated bundle.
            </div>
          )}
          {props.observation.reportText && spans.length === 0 ? (
            <div className="rounded border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900">
              Evidence quote is available, but exact normalized report highlighting did not match.
            </div>
          ) : null}
          {spans.length > 1 ? (
            <div className="rounded border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900">
              Evidence quote matched multiple report spans; all exact matches are highlighted.
            </div>
          ) : null}
          <ReportText report={props.bundle.report} spans={spans} />
        </>
      ) : null}
    </section>
  );
}

function ReportText(props: { report: string; spans: Array<{ start: number; end: number }> }) {
  if (props.spans.length === 0) {
    return (
      <pre className="report-text max-h-[420px] overflow-auto whitespace-pre-wrap rounded border border-slate-200 bg-white p-3 text-xs leading-5 text-slate-800">
        {props.report}
      </pre>
    );
  }

  const nodes: React.ReactNode[] = [];
  let cursor = 0;
  props.spans.forEach((span, index) => {
    if (span.start > cursor) {
      nodes.push(props.report.slice(cursor, span.start));
    }
    nodes.push(<mark key={`${span.start}-${index}`}>{props.report.slice(span.start, span.end)}</mark>);
    cursor = span.end;
  });
  if (cursor < props.report.length) {
    nodes.push(props.report.slice(cursor));
  }

  return (
    <pre className="report-text max-h-[420px] overflow-auto whitespace-pre-wrap rounded border border-slate-200 bg-white p-3 text-xs leading-5 text-slate-800">
      {nodes}
    </pre>
  );
}

function MetadataSections(props: { finding: EnrichedFinding }) {
  const definition = props.finding.definition;
  const anatomy = props.finding.anatomy;

  return (
    <div className="grid gap-3 xl:grid-cols-3">
      <section className="rounded border border-slate-200 bg-slate-50 p-3">
        <h2 className="text-sm font-semibold text-slate-950">Instance data</h2>
        <Info label="IPL finding ID" value={props.finding.id} />
        <Info label="Actual location" value={props.finding.locationDisplay} />
        <Info label="Status" value={statusLabel(props.finding.status)} />
        <Info label="Observations" value={`${props.finding.finding.observations.length}`} />
      </section>
      <section className="rounded border border-slate-200 bg-slate-50 p-3">
        <h2 className="text-sm font-semibold text-slate-950">Definition data</h2>
        {definition ? (
          <>
            <Info label="Name" value={definition.name} />
            <Info label="Typical anatomy" value={definition.location?.text || "Not specified"} />
            <Info label="Modalities" value={definition.modalities || "Not specified"} />
            <Info label="Subspecialties" value={definition.subspecialties || "Not specified"} />
            <Info label="Etiologies" value={definition.etiologies || "Not specified"} />
          </>
        ) : (
          <div className="mt-2 text-sm text-slate-600">
            Definition metadata is unavailable for this code.
          </div>
        )}
      </section>
      <section className="rounded border border-slate-200 bg-slate-50 p-3">
        <h2 className="text-sm font-semibold text-slate-950">Anatomy data</h2>
        <Info label="RID" value={props.finding.locationId || "Unlocalized"} />
        <Info label="Region" value={props.finding.regionLabel} />
        <Info label="Sub-region" value={props.finding.clusterLabel} />
        <Info label="Laterality" value={sideLabel(props.finding.laterality)} />
        {anatomy?.containmentAncestors.length ? (
          <Info
            label="Containment path"
            value={anatomy.containmentAncestors.map((ancestor) => ancestor.display).join(" > ")}
          />
        ) : null}
      </section>
    </div>
  );
}

function FindingList(props: {
  findings: EnrichedFinding[];
  onFinding: (finding: EnrichedFinding) => void;
}) {
  if (props.findings.length === 0) {
    return (
      <div className="rounded border border-slate-200 bg-slate-50 p-3 text-sm text-slate-600">
        No findings match the current filters.
      </div>
    );
  }

  return (
    <div className="divide-y divide-slate-200 rounded border border-slate-200">
      {props.findings.map((finding) => (
        <button
          key={finding.id}
          className="block w-full px-3 py-2 text-left hover:bg-cyan-50"
          onClick={() => props.onFinding(finding)}
          data-testid={`finding-${finding.id}`}
        >
          <div className="flex items-start justify-between gap-3">
            <div>
              <div className="font-medium text-slate-950" title={finding.display}>
                {finding.compactDisplay}
              </div>
              <div className="text-xs text-slate-600">
                {finding.locationDisplay} | {finding.code}
              </div>
            </div>
            <StatusBadge status={finding.status} />
          </div>
        </button>
      ))}
    </div>
  );
}

function DetailHeader(props: {
  title: string;
  subtitle?: string;
  onBack?: () => void;
  backLabel?: string;
}) {
  return (
    <div className="flex items-start justify-between gap-3 border-b border-slate-200 pb-3">
      <div>
        <h1 className="text-xl font-semibold text-slate-950">{props.title}</h1>
        {props.subtitle ? <p className="mt-1 text-sm text-slate-600">{props.subtitle}</p> : null}
      </div>
      {props.onBack ? (
        <button
          className="rounded border border-slate-300 px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50"
          onClick={props.onBack}
        >
          {props.backLabel || "Back"}
        </button>
      ) : null}
    </div>
  );
}

function SideBreakdown(props: { findings: EnrichedFinding[] }) {
  return (
    <div className="mt-2 grid grid-cols-4 gap-1 text-[11px] text-slate-600">
      <span>R {props.findings.filter((finding) => finding.laterality === "right").length}</span>
      <span>Mid {props.findings.filter((finding) => finding.laterality === "midline_nonlateral").length}</span>
      <span>Gen {props.findings.filter((finding) => finding.laterality === "generic_unspecified").length}</span>
      <span>L {props.findings.filter((finding) => finding.laterality === "left").length}</span>
    </div>
  );
}

function Metric(props: { label: string; value: number }) {
  return (
    <div className="rounded border border-slate-200 bg-slate-50 p-3">
      <div className="text-2xl font-semibold text-slate-950">{props.value}</div>
      <div className="text-xs font-medium uppercase text-slate-500">{props.label}</div>
    </div>
  );
}

function Info(props: { label: string; value: string }) {
  return (
    <div className="mt-2">
      <div className="text-[11px] font-semibold uppercase text-slate-500">{props.label}</div>
      <div className="break-words text-sm text-slate-800">{props.value}</div>
    </div>
  );
}

function StatusBadge(props: { status: Status }) {
  return (
    <span
      className={`shrink-0 rounded px-2 py-1 text-xs font-semibold ring-1 ${statusTone(
        props.status,
      )}`}
    >
      {statusLabel(props.status)}
    </span>
  );
}

function WarningList(props: { warnings: WarningRecord[] }) {
  return (
    <section className="rounded border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900">
      <h2 className="font-semibold">Generated data warnings</h2>
      <ul className="mt-2 list-disc space-y-1 pl-5">
        {props.warnings.map((warning, index) => (
          <li key={`${warning.type}-${index}`}>{warning.message}</li>
        ))}
      </ul>
    </section>
  );
}

export default App;
