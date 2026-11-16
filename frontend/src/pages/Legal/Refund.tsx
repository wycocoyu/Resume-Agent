import { LegalLayout, LegalSection, LegalList, SUPPORT_EMAIL } from './LegalLayout'

const LAST_UPDATED = '2026 年 6 月 23 日'

export default function Refund() {
  return (
    <LegalLayout title="退款政策" lastUpdated={LAST_UPDATED}>
      <LegalSection heading="1. 适用范围">
        <p>
          本退款政策适用于 CocoCV（以下简称“本服务”）提供的付费功能及一次性数字额度包（积分包）。就前述付费项目的购买，本政策所载规则供您在购买前参阅，并对相关交易适用。
        </p>
      </LegalSection>

      <LegalSection heading="2. 数字产品性质">
        <p>
          本服务销售的为数字产品（如 AI 简历额度、导出额度等），购买后即时交付并可立即使用。由于数字产品的特殊性，一经使用通常无法退回，请您在购买前确认所选商品与数量。
        </p>
      </LegalSection>

      <LegalSection heading="3. 可退款情形">
        <p>出现以下情况时，您可申请退款：</p>
        <LegalList
          items={[
            '因系统故障导致重复扣款或扣款金额错误；',
            '付费额度因我方技术原因完全无法使用，且未被实际消耗；',
            '适用法律法规明确要求退款的其他情形。',
          ]}
        />
      </LegalSection>

      <LegalSection heading="4. 不可退款情形">
        <LegalList
          items={[
            '额度已部分或全部使用；',
            '因个人主观偏好（如对 AI 生成结果不满意）而非服务故障提出的退款；',
            '违反《服务条款》导致账户被限制或终止的情形。',
          ]}
        />
      </LegalSection>

      <LegalSection heading="5. 申请方式">
        <p>
          如需申请退款，请通过{' '}
          <a className="text-blue-600 dark:text-blue-400 hover:underline" href={`mailto:${SUPPORT_EMAIL}`}>
            {SUPPORT_EMAIL}
          </a>{' '}
          联系我们，并提供订单号、注册邮箱与退款原因，以便我们核实处理。
        </p>
      </LegalSection>

      <LegalSection heading="6. 处理时效">
        <p>
          我们将在收到完整退款申请后的合理工作日内完成审核。审核通过的退款将原路退回至您的支付渠道，实际到账时间取决于支付服务商与银行的处理周期。
        </p>
      </LegalSection>

      <LegalSection heading="7. 政策变更">
        <p>
          我们可能随付费功能的上线与调整更新本政策。重大变更将通过站内提示或购买页面告知，并自公布之时起对其后发生的购买生效。
        </p>
      </LegalSection>

      <LegalSection heading="8. 联系我们">
        <p>
          如对本退款政策有任何疑问，请通过{' '}
          <a className="text-blue-600 dark:text-blue-400 hover:underline" href={`mailto:${SUPPORT_EMAIL}`}>
            {SUPPORT_EMAIL}
          </a>{' '}
          与我们联系。
        </p>
      </LegalSection>
    </LegalLayout>
  )
}
