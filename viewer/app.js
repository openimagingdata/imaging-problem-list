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
        examTypeMappings: {},

        // Filters
        filterStatus: 'all', // 'all', 'current', 'resolved', 'ever-present', 'never'
        filterRegion: 'all',

        // Initialization
        async init() {
            console.log('Initializing IPL App...');
            await this.loadExamTypeMappings();
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

        // Load exam type mappings
        async loadExamTypeMappings() {
            try {
                const response = await fetch('data/exam_type_mappings.json');
                this.examTypeMappings = await response.json();
                console.log('Loaded exam type mappings:', this.examTypeMappings);
            } catch (error) {
                console.error('Error loading exam type mappings:', error);
                this.examTypeMappings = {};
            }
        },

        // Load patients list
        async loadPatients() {
            try {
                const response = await fetch('data/patients.json');
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
                const patientResponse = await fetch(`data/patients/${patientId}/patient.json`);
                this.currentPatient = await patientResponse.json();

                // Load IPL
                const iplResponse = await fetch(`data/patients/${patientId}/ipl.json`);
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
            const allPresent = finding.observations.every(obs => obs.presence === 'present');

            if (mostRecent.presence === 'present') {
                // Present on most recent
                if (allPresent && finding.observations.length > 1) {
                    return { status: 'always', label: 'Always' };
                } else {
                    return { status: 'current', label: 'Current' };
                }
            } else if (hasEverBeenPresent) {
                // Was present before, now absent = resolved
                return { status: 'resolved', label: 'Resolved' };
            } else {
                // Never present
                return { status: 'never', label: 'Never' };
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

        // Get short exam name from mapping, fallback to original
        getShortExamName(fullName) {
            return this.examTypeMappings[fullName] || fullName;
        },

        // Group observations by report_id and sort by date (most recent first)
        getGroupedObservations(finding) {
            if (!finding.observations || finding.observations.length === 0) {
                return [];
            }

            // Group by report_id
            const groups = {};
            finding.observations.forEach(obs => {
                if (!groups[obs.report_id]) {
                    groups[obs.report_id] = {
                        report_id: obs.report_id,
                        exam_date: obs.exam_date,
                        exam_type_display: obs.exam_type_display,
                        observations: [],
                        count: 0
                    };
                }
                groups[obs.report_id].observations.push(obs);
                groups[obs.report_id].count++;
            });

            // Convert to array and sort by date (most recent first)
            const groupedArray = Object.values(groups).sort((a, b) =>
                new Date(b.exam_date) - new Date(a.exam_date)
            );

            // Determine presence status for each group
            groupedArray.forEach(group => {
                // If any observation is present, mark the group as present
                const hasPresent = group.observations.some(obs => obs.presence === 'present');
                group.presence = hasPresent ? 'present' : 'absent';

                // Combine all report texts from observations in this group
                group.reportText = group.observations
                    .map(obs => obs.reportText)
                    .filter(text => text) // Remove any null/undefined
                    .join('\n\n');

                // Create a unique ID for popovers
                group.popoverId = 'popover-group-' + group.report_id;
            });

            return groupedArray;
        },

        // Filtered findings based on current filters
        get filteredFindings() {
            let findings = this.ipl.findings;

            // Filter by status
            if (this.filterStatus !== 'all') {
                findings = findings.filter(finding => {
                    switch (this.filterStatus) {
                        case 'current':
                            return finding.status === 'current' || finding.status === 'always';
                        case 'resolved':
                            return finding.status === 'resolved';
                        case 'ever-present':
                            return finding.status === 'current' || finding.status === 'always' || finding.status === 'resolved';
                        case 'never':
                            return finding.status === 'never';
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
                const response = await fetch(`data/patients/${this.currentPatient.id}/exams/${reportId}/efl.json`);
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
                const response = await fetch(`data/patients/${this.currentPatient.id}/exams/${reportId}/report.txt`);
                this.currentReport = await response.text();
                this.currentView = 'report';
                console.log('Loaded report');
            } catch (error) {
                console.error('Error loading report:', error);
            }

            this.loading = false;
        }
    };
}
