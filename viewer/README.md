# Imaging Problem List Viewer

A lightweight, static web application for visualizing patient imaging findings across multiple exams.

## Features

- **Dark Mode First**: Designed for radiologists with dark mode as the default
- **Three-Level Navigation**: IPL → EFL → Report
- **Temporal Status Tracking**: Distinguish between currently present, resolved, and always-absent findings
- **Smart Filtering**: Filter by status (present, resolved, ever-present, ruled out) and body region
- **Multi-Patient Support**: Easily switch between patients via dropdown or URL parameters

## Technology Stack

- **HTML5** - Structure
- **Tailwind CSS** - Styling (via CDN)
- **Flowbite** - UI components (via CDN)
- **Alpine.js** - Reactivity and interactivity (via CDN)

**No build step required!** Just open `index.html` in a web browser.

## Getting Started

### Option 1: Open Locally
```bash
# From the viewer directory
open index.html
# or
python3 -m http.server 8000
# Then navigate to http://localhost:8000
```

### Option 2: Use a Simple HTTP Server
```bash
# Python 3
cd viewer
python3 -m http.server 8000

# Node.js (with npx)
npx http-server viewer -p 8000

# PHP
cd viewer
php -S localhost:8000
```

Then open your browser to `http://localhost:8000`

## Data Structure

The viewer expects data organized in the following structure:

```
data/
  patients.json              # Manifest of all patients
  patients/
    patient-mrn0000001/
      patient.json           # Patient metadata
      ipl.json              # Imaging Problem List
      exams/
        <report-id>/
          efl.json          # Exam Finding List
          report.txt        # Raw report text
```

### patients.json Format
```json
{
  "patients": [
    {
      "id": "patient-mrn0000001",
      "display_name": "John Doe",
      "mrn": "MRN0000001",
      "dob": "1985-06-15",
      "exam_count": 2
    }
  ]
}
```

## URL Parameters

- `?patient=patient-mrn0000001` - Load specific patient directly
- Future: `?patient=X&exam=Y` - Load specific exam
- Future: `?patient=X&exam=Y&view=report` - Load specific report

## Finding Status Categories

1. **Currently Present** (Green)
   - Most recent observation = "present"

2. **Resolved** (Amber)
   - Has been present in the past
   - Most recent observation = "absent"

3. **Not Present / Ruled Out** (Gray)
   - All observations = "absent"
   - Never documented as present

## Body Region Inference

The viewer automatically categorizes findings by body region based on keywords:

- **Chest**: pulmonary, lung, pleural, mediastinal, coronary, etc.
- **Abdomen**: liver, hepatic, pancreatic, splenic, etc.
- **Pelvis/GU**: urinary, bladder, prostate, calculi, etc.
- **Musculoskeletal**: bone, joint, fracture, osteoporosis, etc.
- **Head/Neck**: brain, intracranial, sinus, etc.

## Browser Support

Works in all modern browsers:
- Chrome/Edge (latest)
- Firefox (latest)
- Safari (latest)

## Development

Since this uses vanilla HTML + CDN resources, you can edit files directly and refresh your browser to see changes. No compilation or build process needed.

## Adding New Patients

1. Create a new directory under `data/patients/`
2. Add `patient.json`, `ipl.json`, and exam subdirectories
3. Update `data/patients.json` to include the new patient
4. Refresh the viewer - the new patient will appear in the dropdown
