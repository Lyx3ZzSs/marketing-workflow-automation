// All records below are fictional and contain no data from the supplied OA document.
export const projects = [
  { id: 'demo-001', code: 'DEMO-2026-001', name: '滨江产业园能源管理系统', customer: '示例 · 澄江园区运营有限公司', location: '杭州市滨江区 · 滨江产业园 A 区', content: '建设园区能源管理平台，接入 A 区楼宇电表、水表和空调设备，实现能耗采集、统计与告警。', owner: '项目一组', stage: '待立项', date: '2026-10-10' },
  { id: 'demo-017', code: 'DEMO-2026-017', name: '滨江产业园能源管理系统', customer: '示例 · 澄江园区运营有限公司', location: '杭州市滨江区 · 滨江产业园 A 区', content: '建设园区能源管理平台，接入 A 区楼宇电表、水表和空调设备，实现能耗采集、统计与告警。', owner: '项目二组', stage: '已立项', date: '2026-09-18' },
  { id: 'demo-002', code: 'DEMO-2026-002', name: '东港物流园视频安防升级', customer: '示例 · 东港物流有限公司', location: '宁波市北仑区 · 东港物流园', content: '升级物流园视频监控系统，新增仓库摄像机、门禁设备及视频存储服务器。', owner: '项目三组', stage: '待立项', date: '2026-10-09' },
  { id: 'demo-009', code: 'DEMO-2026-009', name: '东港物流园视频安防改造', customer: '示例 · 东港物流有限公司', location: '宁波市北仑区 · 东港物流园', content: '改造物流园视频监控系统，新增仓库摄像机、门禁设备及视频存储服务器，涉及一期仓库。', owner: '项目二组', stage: '实施中', date: '2026-08-22' },
  { id: 'demo-003', code: 'DEMO-2026-003', name: '山海展览馆数字导览建设', customer: '示例 · 山海文化发展有限公司', location: '温州市鹿城区 · 山海展览馆', content: '为展览馆建设多语言数字导览小程序，制作展品语音介绍和室内参观路线。', owner: '项目一组', stage: '待立项', date: '2026-10-11' },
  { id: 'demo-004', code: 'DEMO-2026-004', name: '西溪研发中心网络建设', customer: '示例 · 西溪科技有限公司', location: '', content: '建设研发中心办公网络，配置无线接入点、核心交换机与访客网络。', owner: '项目四组', stage: '待立项', date: '2026-10-11' },
];

// Separate sample ledgers keep the "clear" example's comparison scope complete.
export function ledgerFor(code) {
  return code.trim().toUpperCase() === 'DEMO-2026-004' ? projects : projects.filter(p => p.id !== 'demo-004');
}
