export default function Report() {
  return (
    <div className="p-8">
      <div className="max-w-6xl mx-auto">
        <h1 className="text-4xl font-bold text-gray-900 mb-6">Generate Report</h1>
        <p className="text-lg text-gray-600 mb-8">Create comprehensive curriculum alignment reports</p>
        
        <div className="bg-white rounded-lg shadow-md p-6 border border-gray-200 mb-6">
          <h2 className="text-2xl font-semibold text-gray-800 mb-4">Report Configuration</h2>
          
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-2">Report Type</label>
              <select className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500">
                <option>Curriculum Alignment Report</option>
                <option>Skills Gap Analysis</option>
                <option>Job Market Trends</option>
                <option>Course Effectiveness</option>
              </select>
            </div>
            
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-2">Time Period</label>
              <select className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500">
                <option>Last 30 days</option>
                <option>Last 3 months</option>
                <option>Last 6 months</option>
                <option>Last year</option>
              </select>
            </div>
            
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-2">Department</label>
              <select className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500">
                <option>All Departments</option>
                <option>Computer Science</option>
                <option>Engineering</option>
                <option>Business</option>
              </select>
            </div>
            
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-2">Format</label>
              <select className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500">
                <option>PDF</option>
                <option>Excel</option>
                <option>CSV</option>
              </select>
            </div>
          </div>
          
          <div className="mt-6 flex space-x-4">
            <button className="px-6 py-3 bg-blue-600 text-white rounded-md hover:bg-blue-700 transition-colors font-medium">
              Generate Report
            </button>
            <button className="px-6 py-3 bg-gray-200 text-gray-800 rounded-md hover:bg-gray-300 transition-colors font-medium">
              Preview
            </button>
          </div>
        </div>
        
        <div className="bg-white rounded-lg shadow-md p-6 border border-gray-200">
          <h2 className="text-2xl font-semibold text-gray-800 mb-4">Recent Reports</h2>
          <div className="space-y-3">
            <div className="flex justify-between items-center py-3 border-b border-gray-100">
              <div>
                <h3 className="font-medium text-gray-900">Curriculum Alignment Report - CS Department</h3>
                <p className="text-sm text-gray-600">Generated on Jan 15, 2025</p>
              </div>
              <button className="text-blue-600 hover:text-blue-800 font-medium">Download</button>
            </div>
            <div className="flex justify-between items-center py-3 border-b border-gray-100">
              <div>
                <h3 className="font-medium text-gray-900">Skills Gap Analysis - All Departments</h3>
                <p className="text-sm text-gray-600">Generated on Jan 12, 2025</p>
              </div>
              <button className="text-blue-600 hover:text-blue-800 font-medium">Download</button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
