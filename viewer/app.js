function iplApp() {
    return {
        // State
        patients: [],

        // Track which finding popover is currently open (by finding code)
        // Used to ensure only one popover is open at a time across the app
        openFindingPopover: null,

        // Info object for the currently open popover (loaded when popover opens)
        openFindingInfo: null,

        // Bounding rect of the element that triggered the popover (for positioning)
        popoverAnchorRect: null,

        // Popover field definitions for finding info display
        // These are the simple label:value fields rendered via x-for
        // Description, Location (with RadLex ID), and Ontology Codes are handled separately
        popoverFields: [
            { label: 'Synonyms', key: 'synonyms' },
            { label: 'Regions', key: 'regions' },
            { label: 'Modalities', key: 'modalities' },
            { label: 'Subspecialties', key: 'subspecialties' },
            { label: 'Etiologies', key: 'etiologies' },
        ],
        currentPatient: null,
        ipl: { findings: [] },
        currentView: 'ipl', // 'ipl', 'exam', 'report'
        currentExam: null,
        currentEfl: null,
        currentReport: null,
        loading: true,
        examTypeMappings: {},
        findingRegionMappings: {},
        findingDisplayInfo: {},
        highlightedTexts: [],

        // Filters
        filterStatus: 'all', // 'all', 'current', 'resolved', 'ever-present', 'never'
        filterRegion: 'all',

        // Initialization
        async init() {
            console.log('Initializing IPL App...');
            await this.loadExamTypeMappings();
            await this.loadFindingRegionMappings();
            await this.loadFindingDisplayInfo();
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

        // Load finding region mappings
        async loadFindingRegionMappings() {
            try {
                const response = await fetch('data/finding_region_mappings.json');
                this.findingRegionMappings = await response.json();
                console.log('Loaded finding region mappings:', this.findingRegionMappings);
            } catch (error) {
                console.error('Error loading finding region mappings:', error);
                this.findingRegionMappings = {};
            }
        },

        // Load finding display info for popovers
        async loadFindingDisplayInfo() {
            try {
                const response = await fetch('data/finding_display_info.json');
                this.findingDisplayInfo = await response.json();
                console.log('Loaded finding display info:', Object.keys(this.findingDisplayInfo).length, 'findings');
            } catch (error) {
                console.error('Error loading finding display info:', error);
                this.findingDisplayInfo = {};
            }
        },

        // Get finding display info by code
        getFindingDisplayInfo(code) {
            return this.findingDisplayInfo[code] || null;
        },

        // Get a field value from finding info object
        // Used by popover template to access simple string fields
        getInfoFieldValue(info, key) {
            if (!info) return null;
            return info[key] || null;
        },

        // Toggle finding popover - ensures only one is open at a time
        // Now also stores the info object and anchor position for the shared popover
        toggleFindingPopover(findingCode, event) {
            if (this.openFindingPopover === findingCode) {
                this.closeFindingPopover();
            } else {
                this.openFindingPopover = findingCode;
                this.openFindingInfo = this.getFindingDisplayInfo(findingCode);
                // Store anchor position for popover positioning
                if (event) {
                    const anchor = event.target.closest('.relative') || event.target;
                    this.popoverAnchorRect = anchor.getBoundingClientRect();
                }
            }
        },

        // Close any open finding popover
        closeFindingPopover() {
            this.openFindingPopover = null;
            this.openFindingInfo = null;
            this.popoverAnchorRect = null;
        },

        // Check if a specific finding popover should be open
        isFindingPopoverOpen(findingCode) {
            return this.openFindingPopover === findingCode;
        },

        // Get popover positioning style based on current view and anchor element
        // IPL view: popover appears above the finding, or below if near top of viewport
        // Exam view: popover appears to the right of the finding
        getPopoverStyle() {
            if (!this.popoverAnchorRect) return { display: 'none' };
            const rect = this.popoverAnchorRect;

            if (this.currentView === 'ipl') {
                const popoverHeight = 384; // max-h-96 = 24rem = 384px
                const hasRoomAbove = rect.top > popoverHeight + 8;

                if (hasRoomAbove) {
                    // Position above the element
                    return {
                        position: 'fixed',
                        left: rect.left + 'px',
                        top: (rect.top - 8) + 'px',
                        transform: 'translateY(-100%)',
                        zIndex: 100
                    };
                } else {
                    // Position below the element (not enough room above)
                    return {
                        position: 'fixed',
                        left: rect.left + 'px',
                        top: (rect.bottom + 8) + 'px',
                        zIndex: 100
                    };
                }
            } else {
                // Position to the right of the element (like left-full top-0 ml-2)
                return {
                    position: 'fixed',
                    left: (rect.right + 8) + 'px',
                    top: rect.top + 'px',
                    zIndex: 100
                };
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
                        bodyRegions: this.getBodyRegions(finding.finding_type_display)
                    };
                });

                // Update URL
                const url = new URL(window.location);
                url.searchParams.set('patient', patientId);
                window.history.pushState({}, '', url);

                // Reset view
                this.currentView = 'ipl';
                this.currentExam = null;
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

        // Get body regions for a finding
        getBodyRegions(findingTypeDisplay) {
            const mapping = this.findingRegionMappings[findingTypeDisplay];
            if (!mapping) {
                return ['Unknown'];
            }
            return mapping.regions === 'ALL' ? ['ALL'] : mapping.regions;
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
            });

            return groupedArray;
        },

        // Filtered findings based on current filters (region only)
        get filteredFindings() {
            let findings = this.ipl.findings;

            // Filter by body region
            if (this.filterRegion !== 'all') {
                findings = findings.filter(finding =>
                    finding.bodyRegions && (
                        finding.bodyRegions.includes(this.filterRegion) ||
                        finding.bodyRegions.includes('ALL')
                    )
                );
            }

            return findings;
        },

        // Group findings by status for sectioned display
        get groupedFindings() {
            const findings = this.filteredFindings;

            return {
                current: findings.filter(f => f.status === 'current'),
                always: findings.filter(f => f.status === 'always'),
                resolved: findings.filter(f => f.status === 'resolved'),
                never: findings.filter(f => f.status === 'never')
            };
        },

        // Get sections with findings for rendering (eliminates duplication)
        get findingSections() {
            return [
                { title: 'Current', key: 'current', findings: this.groupedFindings.current },
                { title: 'Always', key: 'always', findings: this.groupedFindings.always },
                { title: 'Resolved', key: 'resolved', findings: this.groupedFindings.resolved },
                { title: 'Never', key: 'never', findings: this.groupedFindings.never }
            ].filter(section => section.findings.length > 0);
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
        },

        // Load exam view with split layout
        async loadExamView(reportId) {
            console.log('Loading exam view:', reportId);
            this.loading = true;

            try {
                // Load the EFL for this exam
                const eflResponse = await fetch(`data/patients/${this.currentPatient.id}/exams/${reportId}/efl.json`);
                const efl = await eflResponse.json();

                // Load the report text
                const reportResponse = await fetch(`data/patients/${this.currentPatient.id}/exams/${reportId}/report.txt`);
                const reportText = await reportResponse.text();

                // Find all observations for this report from the IPL
                const examObservations = [];
                this.ipl.findings.forEach(finding => {
                    const obsForThisReport = finding.observations.filter(obs => obs.report_id === reportId);
                    if (obsForThisReport.length > 0) {
                        examObservations.push({
                            finding_type_code: finding.finding_type_code,
                            finding_type_display: finding.finding_type_display,
                            observations: obsForThisReport,
                            count: obsForThisReport.length,
                            reportTexts: obsForThisReport.map(obs => obs.reportText).filter(text => text)
                        });
                    }
                });

                // Compute status for each finding in this exam
                examObservations.forEach(finding => {
                    // Get the full finding from IPL to check overall status
                    const iplFinding = this.ipl.findings.find(f => f.finding_type_code === finding.finding_type_code);
                    if (iplFinding) {
                        const status = this.computeFindingStatus(iplFinding);
                        finding.status = status.status;
                        finding.statusLabel = status.label;
                    }
                });

                // Group findings by status
                const findingSections = [
                    { title: 'Current', key: 'current', findings: examObservations.filter(f => f.status === 'current') },
                    { title: 'Always', key: 'always', findings: examObservations.filter(f => f.status === 'always') },
                    { title: 'Resolved', key: 'resolved', findings: examObservations.filter(f => f.status === 'resolved') },
                    { title: 'Never', key: 'never', findings: examObservations.filter(f => f.status === 'never') }
                ];

                // Get exam metadata from first observation
                const firstObs = examObservations[0]?.observations[0];

                this.currentExam = {
                    report_id: reportId,
                    exam_date: firstObs?.exam_date || efl.examInfo?.studyDateTime?.split('T')[0] || 'Unknown',
                    exam_type_display: firstObs?.exam_type_display || efl.examInfo?.studyDescription || 'Unknown',
                    findings: examObservations,
                    findingSections: findingSections,
                    reportText: reportText
                };

                this.currentView = 'exam';
                console.log('Loaded exam view:', this.currentExam);
                console.log('Finding sections:', findingSections);
                console.log('First finding reportTexts:', examObservations[0]?.reportTexts);
            } catch (error) {
                console.error('Error loading exam view:', error);
            }

            this.loading = false;
        },

        // Highlight text in report
        highlightText(texts) {
            console.log('highlightText called with:', texts);
            this.highlightedTexts = texts || [];

            // Scroll to first highlighted text after DOM updates
            setTimeout(() => {
                const reportContainer = document.querySelector('#report-text');
                const firstMark = reportContainer?.querySelector('mark');
                console.log('First mark element:', firstMark);

                if (firstMark && reportContainer) {
                    // Check if mark is visible in the container
                    const containerRect = reportContainer.getBoundingClientRect();
                    const markRect = firstMark.getBoundingClientRect();

                    const isVisible = (
                        markRect.top >= containerRect.top &&
                        markRect.bottom <= containerRect.bottom
                    );

                    // Only scroll if not visible
                    if (!isVisible) {
                        const markTop = firstMark.offsetTop;
                        const containerHeight = reportContainer.clientHeight;
                        const targetScroll = markTop - (containerHeight / 2);

                        reportContainer.scrollTo({
                            top: targetScroll,
                            behavior: 'smooth'
                        });
                    }
                }
            }, 100);
        },

        // Clear highlighting
        clearHighlight() {
            this.highlightedTexts = [];
        },

        // Format report with highlights
        formatReportWithHighlights(reportText) {
            if (!reportText) return '';

            // Preprocess: Convert ONLY "Findings" and "Impression" to headers
            let preprocessedText = reportText;

            // Convert **Findings** or **Impression** (with or without colon)
            preprocessedText = preprocessedText.replace(/(^|\n)\*\*(Findings|Impression):?\*\*/gi,
                (match, lineStart, word) => `${lineStart}### ${word}`
            );

            // Render Markdown to HTML
            let formattedText = marked.parse(preprocessedText);

            // Apply highlights - need to search across HTML tags
            if (this.highlightedTexts && this.highlightedTexts.length > 0) {
                this.highlightedTexts.forEach(text => {
                    if (text && text.trim()) {
                        // Create a temporary div to work with the HTML
                        const tempDiv = document.createElement('div');
                        tempDiv.innerHTML = formattedText;

                        // Find and highlight text in text nodes
                        this.highlightTextInElement(tempDiv, text);

                        formattedText = tempDiv.innerHTML;
                    }
                });
            }

            return formattedText;
        },

        // Helper function to highlight text across HTML elements
        highlightTextInElement(element, searchText) {
            const walker = document.createTreeWalker(
                element,
                NodeFilter.SHOW_TEXT,
                null,
                false
            );

            const nodesToReplace = [];
            let node;

            // First pass: find all text nodes containing the search text
            while (node = walker.nextNode()) {
                const index = node.textContent.toLowerCase().indexOf(searchText.toLowerCase());
                if (index !== -1) {
                    nodesToReplace.push({ node, index, length: searchText.length });
                }
            }

            // Second pass: replace text nodes with highlighted versions
            nodesToReplace.forEach(({ node, index, length }) => {
                const before = node.textContent.substring(0, index);
                const match = node.textContent.substring(index, index + length);
                const after = node.textContent.substring(index + length);

                const fragment = document.createDocumentFragment();

                if (before) fragment.appendChild(document.createTextNode(before));

                const mark = document.createElement('mark');
                mark.className = 'bg-yellow-300 dark:bg-yellow-600 px-1';
                mark.textContent = match;
                fragment.appendChild(mark);

                if (after) fragment.appendChild(document.createTextNode(after));

                node.parentNode.replaceChild(fragment, node);
            });
        }
    };
}
