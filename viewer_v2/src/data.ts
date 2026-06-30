import type { ExamBundle, PatientsResponse, ViewerData } from "./types";

const dataRoot = `${import.meta.env.BASE_URL}data`;

async function fetchJson<T>(path: string): Promise<T> {
  const response = await fetch(`${dataRoot}${path}`);
  if (!response.ok) {
    throw new Error(`Failed to load ${path}: ${response.status}`);
  }
  return (await response.json()) as T;
}

async function fetchText(path: string): Promise<string> {
  const response = await fetch(`${dataRoot}${path}`);
  if (!response.ok) {
    throw new Error(`Failed to load ${path}: ${response.status}`);
  }
  return response.text();
}

export async function loadViewerData(patientId: string): Promise<ViewerData> {
  const [patients, manifest, anatomyIndex, anatomyClusters, definitions, patient, ipl] =
    await Promise.all([
      fetchJson<PatientsResponse>("/patients.json"),
      fetchJson<ViewerData["manifest"]>("/manifest.json"),
      fetchJson<ViewerData["anatomyIndex"]>("/anatomy_index.json"),
      fetchJson<ViewerData["anatomyClusters"]>("/anatomy_clusters.json"),
      fetchJson<ViewerData["definitions"]>("/finding_display_info.json"),
      fetchJson<ViewerData["patient"]>(`/patients/${patientId}/patient.json`),
      fetchJson<ViewerData["ipl"]>(`/patients/${patientId}/ipl.json`),
    ]);

  return {
    patients: patients.patients,
    patient,
    ipl,
    manifest,
    anatomyIndex,
    anatomyClusters,
    definitions,
  };
}

export async function loadPatients(): Promise<ViewerData["patients"]> {
  const response = await fetchJson<{ patients: ViewerData["patients"] }>("/patients.json");
  return response.patients;
}

export async function loadExamBundle(
  patientId: string,
  reportId: string,
): Promise<ExamBundle> {
  const [efl, report] = await Promise.all([
    fetchJson<ExamBundle["efl"]>(`/patients/${patientId}/exams/${reportId}/efl.json`),
    fetchText(`/patients/${patientId}/exams/${reportId}/report.md`),
  ]);
  return { efl, report };
}
