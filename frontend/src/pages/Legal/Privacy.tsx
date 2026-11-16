import { LegalLayout, LegalSection, LegalList, SUPPORT_EMAIL } from './LegalLayout'

const LAST_UPDATED = '2026 年 6 月 23 日'

export default function Privacy() {
  return (
    <LegalLayout title="隐私政策" lastUpdated={LAST_UPDATED}>
      <LegalSection heading="1. 引言">
        <p>
          本隐私政策说明 CocoCV（以下简称“本服务”）在您使用过程中如何收集、使用、存储与保护您的个人信息。我们重视您的隐私，并按本政策处理您的数据。
        </p>
      </LegalSection>

      <LegalSection heading="2. 我们收集的信息">
        <LegalList
          items={[
            '账户信息：注册或第三方登录时的邮箱、用户名、头像等；',
            '简历内容：您主动输入或上传的姓名、联系方式、教育与工作经历等；',
            '使用信息：为保障服务运行所必需的日志、设备与访问记录；',
            '上传文件：您用于解析的简历 PDF 或文本文件。',
          ]}
        />
      </LegalSection>

      <LegalSection heading="3. 我们如何使用信息">
        <LegalList
          items={[
            '提供并维护简历生成、解析、编辑、分析与导出等核心功能；',
            '通过 AI 模型生成或优化简历内容与建议；',
            '保障账户安全、排查故障与改进服务质量；',
            '在法律要求时履行合规义务。',
          ]}
        />
      </LegalSection>

      <LegalSection heading="4. 存储与第三方服务">
        <p>为实现功能，本服务会将必要数据传输给以下类型的第三方处理者：</p>
        <LegalList
          items={[
            'AI 模型服务商（如 DeepSeek、智谱、豆包）：用于简历内容的生成与分析；',
            '认证服务（BetterAuth、Google 登录）：用于账户登录与会话管理；',
            '云存储（腾讯云 COS）：用于存储头像、照片与简历相关文件。',
          ]}
        />
        <p>我们仅向上述服务传输实现对应功能所必需的数据，并要求其在约定范围内处理。</p>
      </LegalSection>

      <LegalSection heading="5. Cookie 与本地存储">
        <p>
          我们使用 Cookie 与浏览器本地存储维持登录会话、保存编辑草稿与偏好设置。您可通过浏览器设置管理或清除这些数据，但部分功能可能因此无法正常使用。
        </p>
      </LegalSection>

      <LegalSection heading="6. 数据安全">
        <p>
          我们采取合理的技术与管理措施保护您的数据，包括传输加密与访问控制。但请理解，任何通过互联网传输或存储的方式都无法保证绝对安全。
        </p>
      </LegalSection>

      <LegalSection heading="7. 数据保留">
        <p>
          我们在为您提供服务所必需的期间内保留您的个人信息。您注销账户后，我们将在合理期限内删除或匿名化处理相关数据，但法律另有要求的除外。
        </p>
      </LegalSection>

      <LegalSection heading="8. 您的权利">
        <LegalList
          items={[
            '访问、更正或更新您的账户与简历信息；',
            '删除您的简历内容或注销账户；',
            '在适用法律范围内，要求导出您的数据。',
          ]}
        />
      </LegalSection>

      <LegalSection heading="9. 儿童隐私">
        <p>
          本服务面向求职人群，不面向 14 周岁以下的儿童。我们不会主动收集儿童个人信息；如发现误收，将尽快删除。
        </p>
      </LegalSection>

      <LegalSection heading="10. 政策更新">
        <p>
          我们可能不时更新本政策。重大变更将通过站内提示或其他合理方式告知。更新后您继续使用本服务，即视为接受更新后的政策。
        </p>
      </LegalSection>

      <LegalSection heading="11. 联系我们">
        <p>
          如对本政策或您的数据有任何疑问，请通过{' '}
          <a className="text-blue-600 dark:text-blue-400 hover:underline" href={`mailto:${SUPPORT_EMAIL}`}>
            {SUPPORT_EMAIL}
          </a>{' '}
          与我们联系。
        </p>
      </LegalSection>
    </LegalLayout>
  )
}
