// Body region mapping for findings
const BODY_REGION_MAP = {
    chest: ['pulmonary', 'lung', 'pleural', 'mediastinal', 'hilar', 'coronary', 'diaphragm', 'pneumothorax', 'nodule'],
    abdomen: ['liver', 'hepatic', 'pancrea', 'spleen', 'splenic', 'abdom'],
    pelvis: ['urinary', 'bladder', 'prostate', 'uterine', 'pelvi', 'calcul'],
    msk: ['bone', 'joint', 'fracture', 'osteo', 'vertebr', 'skeletal'],
    head: ['brain', 'intracranial', 'sinus', 'cranial', 'cerebr']
};

function iplApp() {
    return {
        // State
        patients: [],
        currentPatient: null,
        ipl: { findings: [] },
        currentView: 'ipl', // 'ipl', 'efl', 'report'
        currentEfl: null,
        currentReport: null,
        loading: true,
        patientDropdownOpen: false,
        isDark: document.documentElement.classList.contains('dark'),

        // Filters
        filterStatus: 'all', // 'all', 'present', 'resolved', 'ever-present', 'ruled-out'
        filterRegion: 'all',

        // Initialization
        async init() {
            console.log('Initializing IPL App...');
            await this.loadPatients();

            // Check URL parameters
            const urlParams = new URLSearchParams(window.location.search);
            const patientId = urlParams.get('patient');

            if (patientId) {
                await this.selectPatient(patientId);
            } else if (this.patients.length > 0) {
                // Default to first patient
                await this.selectPatient(this.patients[0].id);
            }

            this.loading = false;
        },

        // Load patients list
        async loadPatients() {
            try {
                const response = await fetch('../data/patients.json');
                const data = await response.json();
                this.patients = data.patients;
                console.log('Loaded patients:', this.patients);
            } catch (error) {
                console.error('Error loading patients:', error);
            }
        },

        // Select patient and load their IPL
        async selectPatient(patientId) {
            console.log('Selecting patient:', patientId);
            this.loading = true;

            try {
                // Load patient metadata
                const patientResponse = await fetch(`../data/patients/${patientId}/patient.json`);
                this.currentPatient = await patientResponse.json();

                // Load IPL
                const iplResponse = await fetch(`../data/patients/${patientId}/ipl.json`);
                this.ipl = await iplResponse.json();

                // Process findings to add computed status
                this.ipl.findings = this.ipl.findings.map(finding => {
                    const status = this.computeFindingStatus(finding);
                    return {
                        ...finding,
                        status: status.status,
                        statusLabel: status.label,
                        bodyRegion: this.inferBodyRegion(finding.finding_type_display)
                    };
                });

                // Update URL
                const url = new URL(window.location);
                url.searchParams.set('patient', patientId);
                window.history.pushState({}, '', url);

                // Reset view
                this.currentView = 'ipl';
                this.currentEfl = null;
                this.currentReport = null;

                console.log('Loaded IPL:', this.ipl);
            } catch (error) {
                console.error('Error loading patient data:', error);
            }

            this.loading = false;
        },

        // Compute temporal status of a finding
        computeFindingStatus(finding) {
            if (!finding.observations || finding.observations.length === 0) {
                return { status: 'unknown', label: 'Unknown' };
            }

            // Sort observations by date (most recent first)
            const sortedObs = [...finding.observations].sort((a, b) =>
                new Date(b.exam_date) - new Date(a.exam_date)
            );

            const mostRecent = sortedObs[0];
            const hasEverBeenPresent = finding.observations.some(obs => obs.presence === 'present');

            if (mostRecent.presence === 'present') {
                return { status: 'present', label: 'Present' };
            } else if (hasEverBeenPresent) {
                // Was present before, now absent = resolved
                return { status: 'resolved', label: 'Resolved' };
            } else {
                // Always absent = ruled out
                return { status: 'ruled-out', label: 'Not Present' };
            }
        },

        // Infer body region from finding description
        inferBodyRegion(description) {
            const lowerDesc = description.toLowerCase();

            for (const [region, keywords] of Object.entries(BODY_REGION_MAP)) {
                if (keywords.some(keyword => lowerDesc.includes(keyword))) {
                    return region;
                }
            }

            return 'other';
        },

        // Filtered findings based on current filters
        get filteredFindings() {
            let findings = this.ipl.findings;

            // Filter by status
            if (this.filterStatus !== 'all') {
                findings = findings.filter(finding => {
                    switch (this.filterStatus) {
                        case 'present':
                            return finding.status === 'present';
                        case 'resolved':
                            return finding.status === 'resolved';
                        case 'ever-present':
                            return finding.status === 'present' || finding.status === 'resolved';
                        case 'ruled-out':
                            return finding.status === 'ruled-out';
                        default:
                            return true;
                    }
                });
            }

            // Filter by body region
            if (this.filterRegion !== 'all') {
                findings = findings.filter(finding => finding.bodyRegion === this.filterRegion);
            }

            return findings;
        },

        // View finding details (placeholder - could expand to show more info)
        viewFindingDetails(finding) {
            console.log('Viewing finding:', finding);
            // For now, load the most recent exam
            if (finding.observations && finding.observations.length > 0) {
                const sortedObs = [...finding.observations].sort((a, b) =>
                    new Date(b.exam_date) - new Date(a.exam_date)
                );
                this.loadEfl(sortedObs[0].report_id);
            }
        },

        // Load EFL (Exam Finding List)
        async loadEfl(reportId) {
            console.log('Loading EFL:', reportId);
            this.loading = true;

            try {
                const response = await fetch(`../data/patients/${this.currentPatient.id}/exams/${reportId}/efl.json`);
                this.currentEfl = await response.json();
                this.currentView = 'efl';
                console.log('Loaded EFL:', this.currentEfl);
            } catch (error) {
                console.error('Error loading EFL:', error);
            }

            this.loading = false;
        },

        // Load report text
        async viewReport(reportId) {
            console.log('Loading report:', reportId);
            this.loading = true;

            try {
                const response = await fetch(`../data/patients/${this.currentPatient.id}/exams/${reportId}/report.txt`);
                this.currentReport = await response.text();
                this.currentView = 'report';
                console.log('Loaded report');
            } catch (error) {
                console.error('Error loading report:', error);
            }

            this.loading = false;
        },

        // Toggle theme
        toggleTheme() {
            if (document.documentElement.classList.contains('dark')) {
                document.documentElement.classList.remove('dark');
                localStorage.theme = 'light';
                this.isDark = false;
            } else {
                document.documentElement.classList.add('dark');
                localStorage.theme = 'dark';
                this.isDark = true;
            }
        }
    };
}
