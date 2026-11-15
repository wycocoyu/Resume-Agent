import React from 'react';

export interface ProviderLogoProps extends React.SVGProps<SVGSVGElement> {
  size?: number;
  className?: string;
}

/**
 * DeepSeek Vector Logo (Official Whale / Oceanic Wave Glyph)
 */
export const DeepSeekLogo: React.FC<ProviderLogoProps> = ({
  size = 24,
  className = '',
  ...props
}) => (
  <svg
    width={size}
    height={size}
    viewBox="0 0 24 24"
    fill="none"
    xmlns="http://www.w3.org/2000/svg"
    className={className}
    {...props}
  >
    <rect width="24" height="24" rx="5" fill="#1E40AF" fillOpacity="0.1" />
    <path
      d="M19.2 12.8C18.8 11.2 17.5 9.8 15.8 9.3C14.2 8.8 12.4 9.1 11.1 10.1C10.4 10.6 9.8 11.3 9.4 12.1C8.7 11.7 7.9 11.5 7.1 11.6C5.5 11.8 4.2 13 4 14.6C3.8 16.2 4.8 17.7 6.4 18.1C7.8 18.5 9.3 17.9 10.1 16.8C11.5 17.8 13.3 18.1 15 17.6C16.7 17.1 18 15.8 18.6 14.2L20 14.5L19.2 12.8Z"
      fill="#3B82F6"
    />
    <path
      d="M13.5 12C13.5 12.8284 12.8284 13.5 12 13.5C11.1716 13.5 10.5 12.8284 10.5 12C10.5 11.1716 11.1716 10.5 12 10.5C12.8284 10.5 13.5 11.1716 13.5 12Z"
      fill="#60A5FA"
    />
  </svg>
);

/**
 * Zhipu GLM Vector Logo (Geometric Origami Prism)
 */
export const ZhipuLogo: React.FC<ProviderLogoProps> = ({
  size = 24,
  className = '',
  ...props
}) => (
  <svg
    width={size}
    height={size}
    viewBox="0 0 24 24"
    fill="none"
    xmlns="http://www.w3.org/2000/svg"
    className={className}
    {...props}
  >
    <rect width="24" height="24" rx="5" fill="#3859FF" fillOpacity="0.1" />
    <path
      d="M7 6L14 6L17 10L10 10L7 6Z"
      fill="#3859FF"
    />
    <path
      d="M10 10L17 10L14 14L7 14L10 10Z"
      fill="#6881FF"
    />
    <path
      d="M7 14L14 14L17 18L10 18L7 14Z"
      fill="#3859FF"
    />
  </svg>
);

/**
 * OpenAI Vector Logo
 */
export const OpenAILogo: React.FC<ProviderLogoProps> = ({
  size = 24,
  className = '',
  ...props
}) => (
  <svg
    width={size}
    height={size}
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    strokeWidth="1.8"
    strokeLinecap="round"
    strokeLinejoin="round"
    xmlns="http://www.w3.org/2000/svg"
    className={className}
    {...props}
  >
    <path d="M12 2C6.48 2 2 6.48 2 12C2 17.52 6.48 22 12 22C17.52 22 22 17.52 22 12C22 6.48 17.52 2 12 2Z" fill="currentColor" fillOpacity="0.05" />
    <path d="M12 6.5V17.5M6.5 12H17.5M8.1 8.1L15.9 15.9M15.9 8.1L8.1 15.9" stroke="currentColor" />
  </svg>
);

/**
 * Anthropic / Claude Vector Logo
 */
export const AnthropicLogo: React.FC<ProviderLogoProps> = ({
  size = 24,
  className = '',
  ...props
}) => (
  <svg
    width={size}
    height={size}
    viewBox="0 0 24 24"
    fill="none"
    xmlns="http://www.w3.org/2000/svg"
    className={className}
    {...props}
  >
    <rect width="24" height="24" rx="5" fill="#D97706" fillOpacity="0.1" />
    <path
      d="M14.2 6H9.8L5 18H8.5L9.6 15H14.4L15.5 18H19L14.2 6ZM10.5 12.4L12 8.3L13.5 12.4H10.5Z"
      fill="#D97706"
    />
  </svg>
);

/**
 * Google Gemini Vector Logo (4-Point Dynamic Star)
 */
export const GeminiLogo: React.FC<ProviderLogoProps> = ({
  size = 24,
  className = '',
  ...props
}) => (
  <svg
    width={size}
    height={size}
    viewBox="0 0 24 24"
    fill="none"
    xmlns="http://www.w3.org/2000/svg"
    className={className}
    {...props}
  >
    <rect width="24" height="24" rx="5" fill="#4285F4" fillOpacity="0.1" />
    <path
      d="M12 4C12 8.41828 8.41828 12 4 12C8.41828 12 12 15.5817 12 20C12 15.5817 15.5817 12 20 12C15.5817 12 12 8.41828 12 4Z"
      fill="#4285F4"
    />
  </svg>
);

/**
 * Generic Provider Logo Router
 */
export interface GenericProviderLogoProps extends ProviderLogoProps {
  provider: 'deepseek' | 'zhipu' | 'openai' | 'anthropic' | 'gemini' | string;
}

export const ProviderLogo: React.FC<GenericProviderLogoProps> = ({
  provider,
  ...props
}) => {
  const p = (provider || '').toLowerCase();
  switch (p) {
    case 'deepseek':
      return <DeepSeekLogo {...props} />;
    case 'zhipu':
    case 'glm':
      return <ZhipuLogo {...props} />;
    case 'openai':
      return <OpenAILogo {...props} />;
    case 'anthropic':
    case 'claude':
      return <AnthropicLogo {...props} />;
    case 'gemini':
    case 'google':
      return <GeminiLogo {...props} />;
    default:
      return (
        <svg
          width={props.size || 24}
          height={props.size || 24}
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
          className={props.className}
        >
          <rect x="2" y="2" width="20" height="20" rx="5" />
          <path d="M12 8v8" />
          <path d="M8 12h8" />
        </svg>
      );
  }
};
