\NeedsTeXFormat{LaTeX2e}
\ProvidesClass{resume}[2015/05/25 An elegant Résumé class]

% 字体大小只保留一个最终值，避免默认 11pt 覆盖用户选择的 8–10pt
\newcommand{\resumeBaseFontSize}{11pt}
\DeclareOption{8pt}{\renewcommand{\resumeBaseFontSize}{8pt}}
\DeclareOption{9pt}{\renewcommand{\resumeBaseFontSize}{9pt}}
\DeclareOption{10pt}{\renewcommand{\resumeBaseFontSize}{10pt}}
\DeclareOption{11pt}{\renewcommand{\resumeBaseFontSize}{11pt}}
\DeclareOption{12pt}{\renewcommand{\resumeBaseFontSize}{12pt}}
\DeclareOption*{\PassOptionsToClass{\CurrentOption}{extarticle}}
\ProcessOptions\relax

\LoadClass[\resumeBaseFontSize]{extarticle}

% disable indent globally
\setlength{\parindent}{0pt}
% some general improvements, defines the XeTeX logo
\RequirePackage{xltxtra}
% use xifthen
\RequirePackage{xifthen}
% use fontawesome
\RequirePackage{fontawesome}
% use xcolor for customizing color
\RequirePackage[usenames,dvipsnames]{xcolor}
% loading fonts
\RequirePackage{fontspec}
% Main document font
\setmainfont[
  Path = fonts/Main/ ,
  Extension = .otf ,
  UprightFont = *-regular ,
  BoldFont = *-bold ,
  ItalicFont = *-italic ,
  BoldItalicFont = *-bolditalic ,
  SmallCapsFont = Fontin-SmallCaps
]{texgyretermes}

\RequirePackage[
	a4paper,
	left=0.4in,
	right=0.4in,
	top=0.40in,
	bottom=0.4in,
	nohead
]{geometry}

\RequirePackage{titlesec}
\RequirePackage{enumitem}
% hyperref for links：链接不加任何颜色（保持黑色、不干扰排版），但可点击
\RequirePackage[hidelinks]{hyperref}
% ulem：给链接文字加下划线（normalem 避免把 \emph 误变下划线），\uline 支持长 URL 自动换行
\RequirePackage[normalem]{ulem}
% 仓库地址保持正文字体，同时允许在 /、-、_ 等 URL 边界自然换行
\urlstyle{same}
\setlist{noitemsep} % removes spacing from items but leaves space around the whole list
%\setlist{nosep} % removes all vertical spacing within and around the list
\setlist[itemize]{topsep=0.25em, leftmargin=*, labelsep=0.5em, label=\footnotesize$\bullet$, itemindent=0em}
\setlist[enumerate]{topsep=0.25em, leftmargin=1.5pc}
% \RequirePackage[super]{nth}  % 注释掉，如果不需要序数词功能

\titleformat{\section}         % Customise the \section command 
  {\Large\scshape\raggedright} % Make the \section headers large (\Large),
                               % small capitals (\scshape) and left aligned (\raggedright)
  {}{0em}                      % Can be used to give a prefix to all sections, like 'Section ...'
  {}                           % Can be used to insert code before the heading
  [\titlerule]                 % Inserts a horizontal line after the heading
\titlespacing*{\section}{0cm}{*1}{*1}

\titleformat{\subsection}
  {\large\raggedright}
  {}{0em}
  {}
\titlespacing*{\subsection}{0cm}{*1}{*0.5}

% 时间列统一固定宽度（使用绝对单位，避免不同字号导致列宽漂移）
\newcommand{\daterightcolwidth}{4.6cm}
\newcommand{\dateleftcolwidth}{\dimexpr\textwidth-\daterightcolwidth-0.3cm\relax}
\newcommand{\datedtwocol}[2]{%
  \ifthenelse{\isempty{#2}}{%
    \parbox[t]{\textwidth}{\raggedright\strut #1}%
  }{%
    \parbox[t]{\dateleftcolwidth}{\raggedright\strut #1}%
    \hfill
    \parbox[t]{\daterightcolwidth}{\raggedleft\normalsize\strut #2}%
  }%
}
\newcommand{\datedsection}[2]{%
  \section[#1]{\datedtwocol{#1}{#2}}%
}
% 时间线固定宽度右对齐，各模块（教育/实习/项目/开源）严格共用同一列
\newcommand{\datedsubsection}[2]{%
  \subsection[#1]{\datedtwocol{#1}{#2}}%
}
% 开源项目的“标题 + 右侧仓库地址 + 日期”专用排版。
% 标题与仓库地址各自拥有独立列，长链接只在右侧列内换行，不会挤乱项目名。
% 两列使用垂直居中对齐，让较小字号的仓库地址落在项目标题的视觉中线上。
\newcommand{\datedsubsectionwithrepo}[3]{%
  \par\addvspace{1ex}%
  {\large
    \noindent
    \parbox[t]{\dateleftcolwidth}{%
      \parbox[c]{0.48\linewidth}{\raggedright\strut #1}%
      \hfill
      \raisebox{1pt}{\parbox[c]{0.50\linewidth}{\raggedright #2}}%
    }%
    \hfill
    \parbox[t]{\daterightcolwidth}{\raggedleft\normalsize\strut #3}%
    \par
  }%
  \vspace{0.5ex}%
}
\newcommand{\datedline}[2]{%
  {\par\noindent\datedtwocol{#1}{#2}\par}%
}

\newcommand{\name}[1]{
  \centerline{\Huge\scshape{#1}}
  \vspace{1.2ex}
}

\newcommand{\contactInfo}[5]{
  \begin{center}
  \sffamily\small
  {#1}
  \ifthenelse{\isempty{#2}}{}{\textperiodcentered\ \ {#2}}
  \ifthenelse{\isempty{#3}}{}{\textperiodcentered\ \ {#3}}
  \ifthenelse{\isempty{#4}}{}{\textperiodcentered\ \ {#4}}
  \ifthenelse{\isempty{#5}}{}{\textperiodcentered\ \ {#5}}
  \end{center}
  \vspace{-0.8ex}
}

% #1 = 前缀（图标 \faGithub / 文本「博客：」/ 空），#2 = 原始 URL（href 目标与显示）
\newcommand{\blogLine}[2]{
  \ifthenelse{\isempty{#2}}{}{
    \vspace{-0.5ex}
    \centerline{\sffamily\footnotesize #1\href{#2}{#2}}
  }
}

\newcommand{\role}[2]{
  {\par \textit{#1} ~ #2 \par}
  \vspace{0.5ex}
}
