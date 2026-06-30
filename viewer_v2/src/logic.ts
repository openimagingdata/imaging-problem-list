import type {
  AnatomyClusters,
  AnatomyIndex,
  EnrichedFinding,
  FindingDefinitions,
  IplFinding,
  Laterality,
  Observation,
  Status,
  WarningRecord,
} from "./types";

export const activeStatuses: Status[] = ["current", "always"];

export function statusLabel(status: Status): string {
  switch (status) {
    case "always":
      return "Always present";
    case "current":
      return "Current";
    case "resolved":
      return "Resolved";
    case "never_present":
      return "Never present";
  }
}

export function sideLabel(side: Laterality | "all"): string {
  switch (side) {
    case "all":
      return "All sides";
    case "left":
      return "Left";
    case "right":
      return "Right";
    case "midline_nonlateral":
      return "Midline/non-lateral";
    case "generic_unspecified":
      return "Generic/unspecified";
  }
}

export function pickPrimaryLocation(finding: IplFinding): {
  locationId: string | null;
  locationDisplay: string;
} {
  const direct = finding.anatomicLocation;
  if (direct?.locationId) {
    return {
      locationId: direct.locationId,
      locationDisplay: direct.locationDisplay || direct.locationId,
    };
  }

  for (const observation of finding.observations) {
    const location = observation.anatomicLocation;
    if (location?.locationId) {
      return {
        locationId: location.locationId,
        locationDisplay: location.locationDisplay || location.locationId,
      };
    }
  }

  return {
    locationId: null,
    locationDisplay: "Unlocalized",
  };
}

export function enrichFindings(args: {
  findings: IplFinding[];
  statusByFindingId: Record<string, Status>;
  anatomyClusters: AnatomyClusters;
  anatomyIndex: AnatomyIndex;
  definitions: FindingDefinitions;
}): EnrichedFinding[] {
  return args.findings.map((finding) => {
    const location = pickPrimaryLocation(finding);
    const cluster =
      location.locationId !== null
        ? args.anatomyClusters.locationClusters[location.locationId]
        : undefined;
    const anatomy =
      location.locationId !== null ? args.anatomyIndex.locations[location.locationId] : undefined;
    const status = args.statusByFindingId[finding.id];
    const compactDisplay =
      args.definitions.compactNames?.[finding.finding_type_code]?.compact ||
      finding.finding_type_display;

    return {
      finding,
      id: finding.id,
      code: finding.finding_type_code,
      display: finding.finding_type_display,
      compactDisplay,
      status,
      locationId: location.locationId,
      locationDisplay: cluster?.locationDisplay || location.locationDisplay,
      regionId: cluster?.regionId || "unlocalized",
      regionLabel: cluster?.regionLabel || "Unlocalized",
      clusterId: cluster?.clusterId || "unlocalized",
      clusterLabel: cluster?.clusterLabel || "Unlocalized",
      laterality: cluster?.laterality || "generic_unspecified",
      anatomy,
      definition: args.definitions.definitions[finding.finding_type_code],
    };
  });
}

export function countByStatus(findings: EnrichedFinding[]): Record<Status, number> {
  return findings.reduce<Record<Status, number>>(
    (acc, item) => {
      acc[item.status] += 1;
      return acc;
    },
    { current: 0, always: 0, resolved: 0, never_present: 0 },
  );
}

export function activeBurden(findings: EnrichedFinding[]): number {
  return findings.filter((item) => activeStatuses.includes(item.status)).length;
}

export function sortFindings(a: EnrichedFinding, b: EnrichedFinding): number {
  const statusWeight: Record<Status, number> = {
    current: 0,
    always: 1,
    resolved: 2,
    never_present: 3,
  };
  return (
    statusWeight[a.status] - statusWeight[b.status] ||
    a.regionLabel.localeCompare(b.regionLabel) ||
    a.clusterLabel.localeCompare(b.clusterLabel) ||
    a.locationDisplay.localeCompare(b.locationDisplay) ||
    a.display.localeCompare(b.display)
  );
}

export function latestObservation(finding: EnrichedFinding): Observation | null {
  return [...finding.finding.observations].sort((a, b) =>
    (b.exam_date || "").localeCompare(a.exam_date || ""),
  )[0] ?? null;
}

export function uniqueBy<T>(items: T[], keyFor: (item: T) => string): T[] {
  const seen = new Set<string>();
  const result: T[] = [];
  for (const item of items) {
    const key = keyFor(item);
    if (seen.has(key)) {
      continue;
    }
    seen.add(key);
    result.push(item);
  }
  return result;
}

export function warningMatchesFinding(
  warning: WarningRecord,
  findingId: string,
  observationId?: string,
): boolean {
  if (observationId && warning.observationId === observationId) {
    return true;
  }
  return warning.findingId === findingId;
}

export function normalizeWithMap(value: string): {
  normalized: string;
  map: number[];
} {
  let normalized = "";
  const map: number[] = [];
  let inWhitespace = false;

  for (let index = 0; index < value.length; index += 1) {
    const char = foldText(value[index]);
    if (/\s/.test(char)) {
      if (!inWhitespace && normalized.length > 0) {
        normalized += " ";
        map.push(index);
      }
      inWhitespace = true;
      continue;
    }
    for (const foldedChar of char) {
      normalized += foldedChar;
      map.push(index);
    }
    inWhitespace = false;
  }

  return {
    normalized: normalized.trimEnd(),
    map: map.slice(0, normalized.trimEnd().length),
  };
}

function foldText(value: string): string {
  return value
    .normalize("NFKC")
    .replace(/[\u2010\u2011\u2012\u2013\u2014\u2015\u2212]/g, "-")
    .replace(/[\u2018\u2019\u201a\u201b]/g, "'")
    .replace(/[\u201c\u201d\u201e\u201f]/g, '"');
}

export type HighlightSpan = {
  start: number;
  end: number;
};

export function findEvidenceSpans(report: string, evidence?: string): HighlightSpan[] {
  if (!evidence) {
    return [];
  }

  const normalizedEvidence = foldText(evidence).replace(/\s+/g, " ").trim();
  if (!normalizedEvidence) {
    return [];
  }

  const normalizedReport = normalizeWithMap(report);
  const spans: HighlightSpan[] = [];
  let cursor = 0;
  while (cursor <= normalizedReport.normalized.length) {
    const found = normalizedReport.normalized.indexOf(normalizedEvidence, cursor);
    if (found === -1) {
      break;
    }
    const mappedStart = normalizedReport.map[found];
    const mappedEnd = normalizedReport.map[found + normalizedEvidence.length - 1];
    if (mappedStart !== undefined && mappedEnd !== undefined) {
      spans.push({ start: mappedStart, end: mappedEnd + 1 });
    }
    cursor = found + Math.max(normalizedEvidence.length, 1);
  }
  return spans;
}
