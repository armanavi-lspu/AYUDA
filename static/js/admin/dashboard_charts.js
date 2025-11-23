console.log("=== Initializing Dashboard Charts ===");

class DashboardCharts {
    constructor() {
        this.charts = {};
        this.colors = {
            primary: '#4e73df',
            success: '#1cc88a',
            info: '#36b9cc',
            warning: '#f6c23e',
            danger: '#e74a3b',
            secondary: '#858796'
        };
        this.chartColors = [
            '#4e73df', '#1cc88a', '#36b9cc', '#f6c23e', '#e74a3b',
            '#858796', '#6f42c1', '#e83e8c', '#fd7e14', '#20c9a6'
        ];
    }

    initialize() {
        console.log('Starting chart initialization...');
        
        // Check if Chart.js is loaded
        if (typeof Chart === 'undefined') {
            console.error('Chart.js is not loaded!');
            return;
        }
        console.log('Chart.js version:', Chart.version);
        
        this._loadData();
        this._initializeAllCharts();
        console.log('Dashboard charts initialization complete');
    }

    _loadData() {
        console.log('Loading chart data...');
        
        this.monthlyTrendData = this._getJsonData('monthly-trend-data', []);
        console.log('Monthly trend data:', this.monthlyTrendData);
        
        this.statusData = this._getJsonData('status-distribution-data', []);
        console.log('Status data:', this.statusData);
        
        this.programData = this._getJsonData('applications-by-program-data', []);
        console.log('Program data:', this.programData);
        
        this.barangayData = this._getJsonData('barangay-data', []);
        console.log('Barangay data:', this.barangayData);
        
        this.ageData = this._getJsonData('age-distribution-data', []);
        console.log('Age data:', this.ageData);
        
        this.employmentData = this._getJsonData('employment-data', {});
        console.log('Employment data:', this.employmentData);
        
        this.weeklyData = this._getJsonData('weekly-trend-data', []);
        console.log('Weekly data:', this.weeklyData);
    }

    _initializeAllCharts() {
        console.log('Initializing all charts...');
        
        try {
            this._initMonthlyTrendChart();
            this._initStatusPieChart();
            this._initApplicationsByProgramChart();
            this._initBarangayChart();
            this._initAgeDistributionChart();
            this._initEmploymentChart();
            this._initWeeklyTrendChart();
        } catch (error) {
            console.error('Error initializing charts:', error);
        }
    }

    _initMonthlyTrendChart() {
        console.log('Initializing monthly trend chart...');
        const canvas = document.getElementById('monthlyTrendChart');
        
        if (!canvas) {
            console.error('Monthly trend canvas not found!');
            return;
        }
        
        if (!this.monthlyTrendData || this.monthlyTrendData.length === 0) {
            console.warn('No monthly trend data available');
            this._showNoDataMessage(canvas, 'No data available for monthly trend');
            return;
        }

        const ctx = canvas.getContext('2d');
        
        try {
            this.charts.monthlyTrend = new Chart(ctx, {
                type: 'line',
                data: {
                    labels: this.monthlyTrendData.map(d => d.month),
                    datasets: [{
                        label: 'Applications',
                        data: this.monthlyTrendData.map(d => d.count),
                        borderColor: this.colors.primary,
                        backgroundColor: this.colors.primary + '20',
                        borderWidth: 3,
                        fill: true,
                        tension: 0.4,
                        pointRadius: 5,
                        pointHoverRadius: 7,
                        pointBackgroundColor: this.colors.primary,
                        pointBorderColor: '#fff',
                        pointBorderWidth: 2
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {
                        legend: { 
                            display: true,
                            position: 'top'
                        },
                        tooltip: {
                            backgroundColor: 'rgba(0,0,0,0.8)',
                            padding: 12,
                            titleFont: { family: "'Inter', sans-serif" },
                            bodyFont: { family: "'Inter', sans-serif" }
                        }
                    },
                    scales: {
                        y: {
                            beginAtZero: true,
                            ticks: { 
                                precision: 0,
                                font: { family: "'Inter', sans-serif" }
                            }
                        },
                        x: {
                            ticks: {
                                font: { family: "'Inter', sans-serif" }
                            }
                        }
                    }
                }
            });
            console.log('Monthly trend chart created successfully');
        } catch (error) {
            console.error('Error creating monthly trend chart:', error);
        }
    }

    _initStatusPieChart() {
        console.log('Initializing status pie chart...');
        const canvas = document.getElementById('statusPieChart');
        
        if (!canvas) {
            console.error('Status pie canvas not found!');
            return;
        }
        
        if (!this.statusData || this.statusData.length === 0) {
            console.warn('No status data available');
            this._showNoDataMessage(canvas, 'No application status data');
            return;
        }

        const ctx = canvas.getContext('2d');
        const statusColors = {
            'pending': this.colors.warning,
            'approved': this.colors.success,
            'rejected': this.colors.danger,
            'under_review': this.colors.info,
            'submitted': this.colors.secondary
        };

        try {
            this.charts.statusPie = new Chart(ctx, {
                type: 'doughnut',
                data: {
                    labels: this.statusData.map(d => d.status.replace('_', ' ').toUpperCase()),
                    datasets: [{
                        data: this.statusData.map(d => d.count),
                        backgroundColor: this.statusData.map(d => statusColors[d.status] || this.colors.secondary),
                        borderWidth: 2,
                        borderColor: '#fff'
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {
                        legend: {
                            position: 'bottom',
                            labels: { 
                                padding: 15, 
                                boxWidth: 12,
                                font: { family: "'Inter', sans-serif" }
                            }
                        },
                        tooltip: {
                            backgroundColor: 'rgba(0,0,0,0.8)',
                            padding: 12
                        }
                    },
                    cutout: '70%'
                }
            });
            console.log('Status pie chart created successfully');
        } catch (error) {
            console.error('Error creating status pie chart:', error);
        }
    }

    _initApplicationsByProgramChart() {
        console.log('Initializing applications by program chart...');
        const canvas = document.getElementById('applicationsByProgramChart');
        
        if (!canvas) {
            console.error('Applications by program canvas not found!');
            return;
        }
        
        if (!this.programData || this.programData.length === 0) {
            console.warn('No program data available');
            this._showNoDataMessage(canvas, 'No program application data');
            return;
        }

        const ctx = canvas.getContext('2d');
        
        try {
            this.charts.applicationsByProgram = new Chart(ctx, {
                type: 'bar',
                data: {
                    labels: this.programData.map(d => d.program_type),
                    datasets: [{
                        label: 'Applications',
                        data: this.programData.map(d => d.count),
                        backgroundColor: this.colors.info,
                        borderColor: this.colors.info,
                        borderWidth: 1
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {
                        legend: { display: false }
                    },
                    scales: {
                        y: {
                            beginAtZero: true,
                            ticks: { precision: 0 }
                        }
                    }
                }
            });
            console.log('Applications by program chart created successfully');
        } catch (error) {
            console.error('Error creating applications by program chart:', error);
        }
    }

    _initBarangayChart() {
        console.log('Initializing barangay chart...');
        const canvas = document.getElementById('barangayChart');
        
        if (!canvas) {
            console.error('Barangay canvas not found!');
            return;
        }
        
        if (!this.barangayData || this.barangayData.length === 0) {
            console.warn('No barangay data available');
            this._showNoDataMessage(canvas, 'No barangay data');
            return;
        }

        const ctx = canvas.getContext('2d');
        
        try {
            this.charts.barangay = new Chart(ctx, {
                type: 'bar',
                data: {
                    labels: this.barangayData.map(d => d.barangay),
                    datasets: [{
                        label: 'Applications',
                        data: this.barangayData.map(d => d.count),
                        backgroundColor: this.colors.success,
                        borderWidth: 1
                    }]
                },
                options: {
                    indexAxis: 'y',
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {
                        legend: { display: false }
                    },
                    scales: {
                        x: {
                            beginAtZero: true,
                            ticks: { precision: 0 }
                        }
                    }
                }
            });
            console.log('Barangay chart created successfully');
        } catch (error) {
            console.error('Error creating barangay chart:', error);
        }
    }

    _initAgeDistributionChart() {
        console.log('Initializing age distribution chart...');
        const canvas = document.getElementById('ageDistributionChart');
        
        if (!canvas) {
            console.error('Age distribution canvas not found!');
            return;
        }
        
        if (!this.ageData || this.ageData.length === 0) {
            console.warn('No age data available');
            this._showNoDataMessage(canvas, 'No age distribution data');
            return;
        }

        const ctx = canvas.getContext('2d');
        
        try {
            this.charts.ageDistribution = new Chart(ctx, {
                type: 'bar',
                data: {
                    labels: this.ageData.map(d => d.age_group),
                    datasets: [{
                        label: 'Applicants',
                        data: this.ageData.map(d => d.count),
                        backgroundColor: this.chartColors.slice(0, this.ageData.length),
                        borderWidth: 1
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {
                        legend: { display: false }
                    },
                    scales: {
                        y: {
                            beginAtZero: true,
                            ticks: { precision: 0 }
                        }
                    }
                }
            });
            console.log('Age distribution chart created successfully');
        } catch (error) {
            console.error('Error creating age distribution chart:', error);
        }
    }

    _initEmploymentChart() {
        console.log('Initializing employment chart...');
        const canvas = document.getElementById('employmentChart');
        
        if (!canvas) {
            console.error('Employment canvas not found!');
            return;
        }
        
        if (!this.employmentData) {
            console.warn('No employment data available');
            this._showNoDataMessage(canvas, 'No employment data');
            return;
        }

        const ctx = canvas.getContext('2d');
        
        try {
            this.charts.employment = new Chart(ctx, {
                type: 'doughnut',
                data: {
                    labels: ['Employed', 'Unemployed', 'Student', 'Solo Parent'],
                    datasets: [{
                        data: [
                            this.employmentData.employed || 0,
                            this.employmentData.unemployed || 0,
                            this.employmentData.student || 0,
                            this.employmentData.solo_parent || 0
                        ],
                        backgroundColor: [
                            this.colors.success,
                            this.colors.danger,
                            this.colors.info,
                            this.colors.warning
                        ],
                        borderWidth: 2,
                        borderColor: '#fff'
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {
                        legend: {
                            position: 'bottom',
                            labels: { padding: 15, boxWidth: 12 }
                        }
                    },
                    cutout: '60%'
                }
            });
            console.log('Employment chart created successfully');
        } catch (error) {
            console.error('Error creating employment chart:', error);
        }
    }

    _initWeeklyTrendChart() {
        console.log('Initializing weekly trend chart...');
        const canvas = document.getElementById('weeklyTrendChart');
        
        if (!canvas) {
            console.error('Weekly trend canvas not found!');
            return;
        }
        
        if (!this.weeklyData || this.weeklyData.length === 0) {
            console.warn('No weekly data available');
            this._showNoDataMessage(canvas, 'No weekly trend data');
            return;
        }

        const ctx = canvas.getContext('2d');
        
        try {
            this.charts.weeklyTrend = new Chart(ctx, {
                type: 'line',
                data: {
                    labels: this.weeklyData.map(d => d.day),
                    datasets: [{
                        label: 'Applications',
                        data: this.weeklyData.map(d => d.count),
                        borderColor: this.colors.success,
                        backgroundColor: this.colors.success + '20',
                        borderWidth: 3,
                        fill: true,
                        tension: 0.4,
                        pointRadius: 6,
                        pointHoverRadius: 8,
                        pointBackgroundColor: this.colors.success,
                        pointBorderColor: '#fff',
                        pointBorderWidth: 2
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {
                        legend: { display: false }
                    },
                    scales: {
                        y: {
                            beginAtZero: true,
                            ticks: { precision: 0 }
                        }
                    }
                }
            });
            console.log('Weekly trend chart created successfully');
        } catch (error) {
            console.error('Error creating weekly trend chart:', error);
        }
    }

    _showNoDataMessage(canvas, message) {
        const container = canvas.parentElement;
        const messageDiv = document.createElement('div');
        messageDiv.className = 'text-center py-5 text-muted';
        messageDiv.innerHTML = `
            <i class="fas fa-chart-bar fa-3x mb-3 opacity-50"></i>
            <p>${message}</p>
        `;
        canvas.style.display = 'none';
        container.appendChild(messageDiv);
    }

    _getJsonData(elementId, defaultValue = []) {
        try {
            const element = document.getElementById(elementId);
            if (!element) {
                console.warn(`Element '${elementId}' not found`);
                return defaultValue;
            }
            
            const textContent = element.textContent.trim();
            if (!textContent) {
                console.warn(`Element '${elementId}' is empty`);
                return defaultValue;
            }
            
            const data = JSON.parse(textContent);
            return data !== null && data !== undefined ? data : defaultValue;
        } catch (e) {
            console.error(`Error parsing ${elementId}:`, e);
            return defaultValue;
        }
    }
}

// Initialize when DOM is ready
console.log('Document ready state:', document.readyState);

function initDashboard() {
    console.log('Initializing dashboard...');
    const dashboardCharts = new DashboardCharts();
    window.dashboardCharts = dashboardCharts;
    dashboardCharts.initialize();
}

if (document.readyState === 'complete' || document.readyState === 'interactive') {
    initDashboard();
} else {
    document.addEventListener('DOMContentLoaded', initDashboard);
}