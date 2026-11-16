import { LegalLayout, LegalSection, LegalList, SUPPORT_EMAIL } from './LegalLayout'

const LAST_UPDATED = '2026 年 6 月 23 日'

export default function Terms() {
  return (
    <LegalLayout title="服务条款" lastUpdated={LAST_UPDATED}>
      <LegalSection heading="1. 服务说明">
        <p>
          CocoCV（以下简称“本服务”）是一款面向中文求职场景的 AI 简历工具，提供自然语言生成、简历解析、结构化编辑、AI 对话式修改、实时预览、简历质量分析与 PDF 导出等功能。您使用本服务即表示已阅读、理解并同意本条款的全部内容。
        </p>
      </LegalSection>

      <LegalSection heading="2. 账户与登录">
        <p>
          您可通过邮箱注册或第三方账号（如 Google）登录本服务。您有责任妥善保管账户凭据，并对账户下发生的所有活动负责。如发现账户被未授权使用，请及时联系我们。
        </p>
      </LegalSection>

      <LegalSection heading="3. 用户内容与责任">
        <p>您对自己上传、输入或生成的简历内容（包括个人信息、工作经历、教育背景等）拥有全部权利并承担全部责任。您承诺：</p>
        <LegalList
          items={[
            '您填写的信息真实、合法，且不侵犯任何第三方权利；',
            '您不会上传违法、虚假、诽谤或含有恶意代码的内容；',
            '您理解简历内容的真实性由您本人保证，本服务不对其准确性背书。',
          ]}
        />
      </LegalSection>

      <LegalSection heading="4. 可接受使用">
        <p>使用本服务时，您不得：</p>
        <LegalList
          items={[
            '以自动化手段大规模抓取、攻击或干扰服务正常运行；',
            '试图绕过认证、访问他人账户或未授权数据；',
            '将本服务用于任何违反所在地法律法规的用途。',
          ]}
        />
      </LegalSection>

      <LegalSection heading="5. AI 生成内容">
        <p>
          本服务借助第三方大语言模型生成简历文本与建议。AI 生成的内容可能存在不准确、不完整或不适用的情形，仅供参考。您应在采用前自行核对、编辑与确认。本服务不对 AI 生成内容导致的任何求职结果承担责任。
        </p>
      </LegalSection>

      <LegalSection heading="6. 知识产权">
        <p>
          本服务的软件、界面、设计与品牌标识归本服务及其权利人所有。您通过本服务创建的简历内容归您所有；为提供功能所必需，您授予本服务在服务范围内存储、处理与展示该内容的有限许可。
        </p>
      </LegalSection>

      <LegalSection heading="7. 付费服务">
        <p>
          本服务提供付费功能及一次性额度包（积分包）。相关计费、权益与退款规则以购买页面及《退款政策》所载为准，并在您确认后生效。
        </p>
      </LegalSection>

      <LegalSection heading="8. 服务变更与终止">
        <p>
          我们可能不时更新、调整或停止部分功能。若您违反本条款，我们有权限制或终止您对本服务的访问。您也可随时停止使用并注销账户。
        </p>
      </LegalSection>

      <LegalSection heading="9. 免责声明">
        <p>
          本服务按“现状”提供，不对其不中断、无错误或完全满足您的特定需求作出保证。在法律允许的范围内，我们不对因使用或无法使用本服务而产生的间接、附带或后果性损失负责。
        </p>
      </LegalSection>

      <LegalSection heading="10. 责任限制">
        <p>
          在适用法律允许的最大范围内，本服务就本条款及您使用本服务所承担的累计责任，不超过您在主张产生前 12 个月内就本服务实际支付的费用（若为免费使用则以零计）。
        </p>
      </LegalSection>

      <LegalSection heading="11. 条款修订">
        <p>
          我们可能不时修订本条款。重大变更将通过站内提示或其他合理方式告知。修订后您继续使用本服务，即视为接受更新后的条款。
        </p>
      </LegalSection>

      <LegalSection heading="12. 联系我们">
        <p>
          如对本条款有任何疑问，请通过{' '}
          <a className="text-blue-600 dark:text-blue-400 hover:underline" href={`mailto:${SUPPORT_EMAIL}`}>
            {SUPPORT_EMAIL}
          </a>{' '}
          与我们联系。
        </p>
      </LegalSection>
    </LegalLayout>
  )
}
