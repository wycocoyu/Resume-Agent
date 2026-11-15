/**
 * Pure SVG 3D Equilateral Triangle Radar Chart.
 *
 * Feature 18 / Issue #54.
 * Zero external dependencies (no Recharts, Chart.js, ECharts, or D3).
 */
import React from 'react'

export interface RadarDimension {
  key: 'technical' | 'project' | 'experience'
  name: string
  score: number // 0 - 100
  weight?: number // 0.4, 0.35, 0.25
  reasons?: string[]
}

export interface JdRadarChartProps {
  dimensions: RadarDimension[]
  overallScore: number
  size?: number
  className?: string
}

export const RADAR_CENTER_X = 150
export const RADAR_CENTER_Y = 140
export const RADAR_RADIUS = 95

// Angles: [Top (-90 deg), Bottom-Right (30 deg), Bottom-Left (150 deg)]
export const RADAR_ANGLES = [-Math.PI / 2, Math.PI / 6, (5 * Math.PI) / 6]

export function getVertexCoordinate(level: number, angleIndex: number): { x: number; y: number } {
  const angle = RADAR_ANGLES[angleIndex % 3]
  const x = RADAR_CENTER_X + level * RADAR_RADIUS * Math.cos(angle)
  const y = RADAR_CENTER_Y + level * RADAR_RADIUS * Math.sin(angle)
  return { x: Math.round(x * 100) / 100, y: Math.round(y * 100) / 100 }
}

export function getRingPointsString(level: number): string {
  return [0, 1, 2]
    .map((i) => {
      const { x, y } = getVertexCoordinate(level, i)
      return `${x},${y}`
    })
    .join(' ')
}

export function getDataPointsString(dimensions: RadarDimension[]): string {
  const dimMap: Record<string, number> = {
    technical: 75,
    project: 70,
    experience: 80,
  }
  dimensions.forEach((d) => {
    dimMap[d.key] = d.score
  })

  const scores = [dimMap.technical ?? 50, dimMap.project ?? 50, dimMap.experience ?? 50]

  return scores
    .map((rawScore, idx) => {
      const clamped = Math.max(10, Math.min(100, rawScore))
      const norm = clamped / 100
      const { x, y } = getVertexCoordinate(norm, idx)
      return `${x},${y}`
    })
    .join(' ')
}

export const JdRadarChart: React.FC<JdRadarChartProps> = ({
  dimensions,
  overallScore,
  size = 300,
  className = '',
}) => {
  const levels = [0.25, 0.5, 0.75, 1.0]
  const polygonPoints = getDataPointsString(dimensions)

  const dimNames = {
    technical: '技术匹配度',
    project: '项目契合度',
    experience: '资历契合度',
  }

  const technicalDim = dimensions.find((d) => d.key === 'technical')
  const projectDim = dimensions.find((d) => d.key === 'project')
  const experienceDim = dimensions.find((d) => d.key === 'experience')

  return (
    <div className={`flex flex-col items-center justify-center p-2 select-none ${className}`}>
      <div className="relative" style={{ width: size, height: size * 0.95 }}>
        <svg
          viewBox="0 0 300 280"
          className="w-full h-full overflow-visible drop-shadow-sm"
          aria-label="3D岗位匹配雷达图"
        >
          <defs>
            <linearGradient id="radarFill" x1="0%" y1="0%" x2="100%" y2="100%">
              <stop offset="0%" stopColor="#3b82f6" stopOpacity="0.45" />
              <stop offset="100%" stopColor="#10b981" stopOpacity="0.35" />
            </linearGradient>
            <filter id="glow" x="-20%" y="-20%" width="140%" height="140%">
              <feDropShadow dx="0" dy="2" stdDeviation="3" floodColor="#2563eb" floodOpacity="0.3" />
            </filter>
          </defs>

          {/* Grid rings */}
          {levels.map((level, idx) => (
            <polygon
              key={`ring-${idx}`}
              points={getRingPointsString(level)}
              fill="none"
              stroke="#e2e8f0"
              strokeWidth={idx === levels.length - 1 ? 1.5 : 1}
              strokeDasharray={idx === levels.length - 1 ? 'none' : '4 3'}
              className="dark:stroke-slate-700 transition-all duration-300"
            />
          ))}

          {/* Radial axis lines */}
          {[0, 1, 2].map((idx) => {
            const vertex = getVertexCoordinate(1.0, idx)
            return (
              <line
                key={`axis-${idx}`}
                x1={RADAR_CENTER_X}
                y1={RADAR_CENTER_Y}
                x2={vertex.x}
                y2={vertex.y}
                stroke="#cbd5e1"
                strokeWidth={1.2}
                className="dark:stroke-slate-700"
              />
            )
          })}

          {/* Data area polygon */}
          <polygon
            points={polygonPoints}
            fill="url(#radarFill)"
            stroke="#2563eb"
            strokeWidth="2.5"
            strokeLinejoin="round"
            filter="url(#glow)"
            className="transition-all duration-500 ease-out"
          />

          {/* Data point dots */}
          {[
            { dim: technicalDim, idx: 0 },
            { dim: projectDim, idx: 1 },
            { dim: experienceDim, idx: 2 },
          ].map(({ dim, idx }) => {
            const score = dim ? dim.score : 50
            const norm = Math.max(10, Math.min(100, score)) / 100
            const pt = getVertexCoordinate(norm, idx)
            return (
              <g key={`point-${idx}`}>
                <circle cx={pt.x} cy={pt.y} r={5} fill="#2563eb" stroke="#ffffff" strokeWidth={2} />
              </g>
            )
          })}

          {/* Apex Labels */}
          {/* Top: Technical */}
          <text
            x={150}
            y={24}
            textAnchor="middle"
            className="text-xs font-bold fill-slate-800 dark:fill-slate-200"
          >
            {dimNames.technical}
          </text>
          <text
            x={150}
            y={38}
            textAnchor="middle"
            className="text-[11px] font-mono font-bold fill-blue-600 dark:fill-blue-400"
          >
            {technicalDim ? `${Math.round(technicalDim.score)}分` : '--'}
          </text>

          {/* Bottom Right: Project */}
          <text
            x={240}
            y={205}
            textAnchor="middle"
            className="text-xs font-bold fill-slate-800 dark:fill-slate-200"
          >
            {dimNames.project}
          </text>
          <text
            x={240}
            y={220}
            textAnchor="middle"
            className="text-[11px] font-mono font-bold fill-emerald-600 dark:fill-emerald-400"
          >
            {projectDim ? `${Math.round(projectDim.score)}分` : '--'}
          </text>

          {/* Bottom Left: Experience */}
          <text
            x={60}
            y={205}
            textAnchor="middle"
            className="text-xs font-bold fill-slate-800 dark:fill-slate-200"
          >
            {dimNames.experience}
          </text>
          <text
            x={60}
            y={220}
            textAnchor="middle"
            className="text-[11px] font-mono font-bold fill-purple-600 dark:fill-purple-400"
          >
            {experienceDim ? `${Math.round(experienceDim.score)}分` : '--'}
          </text>

          {/* Center composite score pill */}
          <g transform={`translate(${RADAR_CENTER_X - 28}, ${RADAR_CENTER_Y - 14})`}>
            <rect
              width="56"
              height="28"
              rx="14"
              fill="#ffffff"
              stroke="#2563eb"
              strokeWidth="1.5"
              className="dark:fill-slate-900 shadow-sm"
            />
            <text
              x="28"
              y="18"
              textAnchor="middle"
              className="text-xs font-mono font-black fill-blue-600 dark:fill-blue-400"
            >
              {Math.round(overallScore)}分
            </text>
          </g>
        </svg>
      </div>

      {/* Dimension breakdown cards */}
      <div className="grid grid-cols-3 gap-2 w-full mt-2 text-center text-xs">
        <div className="p-2 rounded border border-slate-200 dark:border-slate-800 bg-blue-50/50 dark:bg-blue-950/20">
          <div className="text-slate-500 dark:text-slate-400 text-[11px]">技术匹配度</div>
          <div className="font-bold text-blue-600 dark:text-blue-400 text-sm font-mono mt-0.5">
            {technicalDim ? Math.round(technicalDim.score) : 0}
          </div>
        </div>
        <div className="p-2 rounded border border-slate-200 dark:border-slate-800 bg-emerald-50/50 dark:bg-emerald-950/20">
          <div className="text-slate-500 dark:text-slate-400 text-[11px]">项目契合度</div>
          <div className="font-bold text-emerald-600 dark:text-emerald-400 text-sm font-mono mt-0.5">
            {projectDim ? Math.round(projectDim.score) : 0}
          </div>
        </div>
        <div className="p-2 rounded border border-slate-200 dark:border-slate-800 bg-purple-50/50 dark:bg-purple-950/20">
          <div className="text-slate-500 dark:text-slate-400 text-[11px]">资历匹配度</div>
          <div className="font-bold text-purple-600 dark:text-purple-400 text-sm font-mono mt-0.5">
            {experienceDim ? Math.round(experienceDim.score) : 0}
          </div>
        </div>
      </div>
    </div>
  )
}
