export type Status = "current" | "always" | "resolved" | "never_present";
export type Laterality =
  | "left"
  | "right"
  | "midline_nonlateral"
  | "generic_unspecified";

export type PatientSummary = {
  id: string;
  displayName: string;
  mrn: string;
  dob?: string;
  examCount: number;
  findingCount: number;
};

export type PatientsResponse = {
  schemaVersion: string;
  generatedAt: string;
  patients: PatientSummary[];
};

export type WarningRecord = {
  type: string;
  message: string;
  findingId?: string;
  observationId?: string;
  reportId?: string;
  locationId?: string;
};

export type Manifest = {
  schemaVersion: string;
  generatedAt: string;
  warnings: WarningRecord[];
  counts: Record<string, number>;
};

export type PatientRecord = PatientSummary & {
  schemaVersion: string;
  generatedAt: string;
};

export type AnatomicRef = {
  id: string;
  display: string;
};

export type AnatomyLocation = {
  id: string;
  display: string;
  regionId: string;
  regionLabel: string;
  laterality: Laterality;
  sourceLaterality?: string | null;
  bodySystem?: string | null;
  structureType?: string | null;
  locationType?: string | null;
  containmentAncestors: AnatomicRef[];
  partOfAncestors: AnatomicRef[];
  genericVariant?: AnatomicRef | null;
  leftVariant?: AnatomicRef | null;
  rightVariant?: AnatomicRef | null;
};

export type AnatomyIndex = {
  schemaVersion: string;
  generatedAt: string;
  locations: Record<string, AnatomyLocation>;
  usedLocationIds: string[];
};

export type RegionConfig = {
  id: string;
  label: string;
  displayOrder: number;
};

export type ClusterConfig = {
  id: string;
  regionId: string;
  label: string;
  displayOrder: number;
  keywords: string[];
};

export type LocationCluster = {
  locationId: string;
  locationDisplay: string;
  regionId: string;
  regionLabel: string;
  clusterId: string;
  clusterLabel: string;
  laterality: Laterality;
  displayOrder: number;
  matchedBy: string;
};

export type AnatomyClusters = {
  schemaVersion: string;
  generatedAt: string;
  regions: RegionConfig[];
  clusters: ClusterConfig[];
  locationClusters: Record<string, LocationCluster>;
};

export type FindingDefinition = {
  code: string;
  name: string;
  description?: string;
  location?: {
    text?: string;
    radlex_id?: string;
  };
  regions?: string;
  modalities?: string;
  subspecialties?: string;
  etiologies?: string;
  ontology_codes?: Array<{
    system: string;
    code: string;
    display: string;
  }>;
  attributes?: string;
};

export type CompactFindingName = {
  name: string;
  compact: string;
};

export type FindingDefinitions = {
  schemaVersion: string;
  generatedAt: string;
  definitions: Record<string, FindingDefinition>;
  compactNames: Record<string, CompactFindingName>;
};

export type Observation = {
  report_id: string;
  observation_id: string;
  exam_date: string;
  exam_type_code: string;
  exam_type_display: string;
  presence: "present" | "absent" | string;
  anatomicLocation?: {
    locationId?: string;
    locationDisplay?: string;
  };
  reportText?: string;
};

export type IplFinding = {
  id: string;
  finding_type_code: string;
  finding_type_display: string;
  anatomicLocation?: {
    locationId?: string;
    locationDisplay?: string;
  };
  observations: Observation[];
};

export type IplRecord = {
  schemaVersion: string;
  patient: {
    id: string;
    name?: string;
    dob?: string;
  };
  findings: IplFinding[];
  viewerMetadata: {
    patientId: string;
    statusByFindingId: Record<string, Status>;
  };
};

export type EflRecord = {
  schemaVersion: string;
  diagnosticReportId: string;
  examInfo?: {
    studyIdentifier?: string;
    studyDateTime?: string;
    studyLoincCode?: string;
    studyDescription?: string;
  };
  findings?: Array<{
    observationId: string;
    findingCode: string;
    findingDescription: string;
    attributes?: Array<{
      attributeDescription: string;
      attributeValueDescription: string;
    }>;
    anatomicLocation?: {
      locationId?: string;
      locationDisplay?: string;
    };
    reportText?: string;
  }>;
};

export type ExamBundle = {
  efl: EflRecord;
  report: string;
};

export type ViewerData = {
  patients: PatientSummary[];
  patient: PatientRecord;
  ipl: IplRecord;
  manifest: Manifest;
  anatomyIndex: AnatomyIndex;
  anatomyClusters: AnatomyClusters;
  definitions: FindingDefinitions;
};

export type EnrichedFinding = {
  finding: IplFinding;
  id: string;
  code: string;
  display: string;
  compactDisplay: string;
  status: Status;
  locationId: string | null;
  locationDisplay: string;
  regionId: string;
  regionLabel: string;
  clusterId: string;
  clusterLabel: string;
  laterality: Laterality;
  anatomy?: AnatomyLocation;
  definition?: FindingDefinition;
};
