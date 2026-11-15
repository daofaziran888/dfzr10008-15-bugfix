import { defineStore } from 'pinia'

// 默认身份与后端种子数据里的「商品归属」同单位，开箱即可维护市场商品；
// 切换到其他渠道组后，市场页的写操作会被后端按跨单位只读拒绝。
export const useSessionStore = defineStore('session', {
  state: () => ({
    operator: '值班管理员',
    operatorUnit: '华东渠道组',
    shiftLabel: '白班 08:00-20:00',
    scope: '数据产品与API工厂',
  }),
  getters: {
    canOperate: (state) => state.operator.length > 0,
  },
  actions: {
    setShift(label: string) {
      this.shiftLabel = label
    },
    setIdentity(operator: string, operatorUnit: string) {
      this.operator = operator
      this.operatorUnit = operatorUnit
    },
  },
})
