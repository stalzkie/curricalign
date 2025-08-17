export default function DatabaseView() {
  return (
    <div className="p-8">
      <div className="max-w-6xl mx-auto">
        <h1 className="text-4xl font-bold text-gray-900 mb-6">Database</h1>
        <p className="text-lg text-gray-600 mb-8">Manage your curriculum and job market data</p>
        
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          <div className="bg-white rounded-lg shadow-md p-6 border border-gray-200">
            <h2 className="text-2xl font-semibold text-gray-800 mb-4">Course Data</h2>
            <div className="space-y-3">
              <div className="flex justify-between items-center py-2 border-b border-gray-100">
                <span className="text-gray-700">Computer Science Courses</span>
                <span className="text-blue-600 font-medium">45 records</span>
              </div>
              <div className="flex justify-between items-center py-2 border-b border-gray-100">
                <span className="text-gray-700">Engineering Courses</span>
                <span className="text-blue-600 font-medium">32 records</span>
              </div>
              <div className="flex justify-between items-center py-2 border-b border-gray-100">
                <span className="text-gray-700">Business Courses</span>
                <span className="text-blue-600 font-medium">28 records</span>
              </div>
            </div>
            <button className="mt-4 px-4 py-2 bg-green-600 text-white rounded-md hover:bg-green-700 transition-colors">
              Add New Course
            </button>
          </div>
          
          <div className="bg-white rounded-lg shadow-md p-6 border border-gray-200">
            <h2 className="text-2xl font-semibold text-gray-800 mb-4">Job Market Data</h2>
            <div className="space-y-3">
              <div className="flex justify-between items-center py-2 border-b border-gray-100">
                <span className="text-gray-700">Tech Jobs</span>
                <span className="text-blue-600 font-medium">1,234 listings</span>
              </div>
              <div className="flex justify-between items-center py-2 border-b border-gray-100">
                <span className="text-gray-700">Engineering Jobs</span>
                <span className="text-blue-600 font-medium">987 listings</span>
              </div>
              <div className="flex justify-between items-center py-2 border-b border-gray-100">
                <span className="text-gray-700">Business Jobs</span>
                <span className="text-blue-600 font-medium">765 listings</span>
              </div>
            </div>
            <button className="mt-4 px-4 py-2 bg-blue-600 text-white rounded-md hover:bg-blue-700 transition-colors">
              Update Data
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
