'use client';

interface MissingSkillsListProps {
  data: string[];
}

export default function MissingSkillsList({ data }: MissingSkillsListProps) {
  return (
    <div className="btn_border_silver h-80">
      <div className="card_background_dark rounded p-6 h-full flex flex-col">
        <h3 className="text-xl font-bold text-white mb-4">Missing Skills</h3>
        <div className="flex-1 overflow-y-auto scrollbar-thin scrollbar-thumb-gray-600 scrollbar-track-gray-800">
          <div className="space-y-2">
            {data.map((skill, index) => (
              <div 
                key={index}
                className="flex items-center justify-between p-3 bg-gray-800/50 rounded-lg border border-gray-700 hover:bg-gray-700/50 transition-colors"
              >
                <span className="text-white font-medium">{skill}</span>
                <div className="flex items-center space-x-2">
                  <span className="text-red-400 text-sm">Missing</span>
                  <div className="w-2 h-2 bg-red-500 rounded-full"></div>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
