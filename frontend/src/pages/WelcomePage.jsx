import styled from 'styled-components';
import { useNavigate } from 'react-router-dom';
import { FiArrowUpRight } from 'react-icons/fi';
import { useI18n } from 'contexts/I18nContext';
import { useUser } from 'contexts/UserContext';
import { NAV_SECTIONS } from 'app/navItems';
import { canViewFor } from 'utils/permissions';

const Wrap = styled.div`
  padding: 28px 20px 56px;

  @media (min-width: 961px) {
    padding: 40px 32px 64px;
  }
`;

const Kicker = styled.div`
  margin-bottom: 6px;
  font-size: 13px;
  font-weight: 600;
  color: ${({ theme }) => (theme.mode === 'dark' ? theme.colors.accentNeon : theme.colors.accent)};
`;

const Title = styled.h1`
  margin: 0 0 8px;
  font-size: clamp(26px, 3.4vw, 34px);
  font-weight: 700;
  line-height: 1.15;
  letter-spacing: -0.025em;
  color: ${({ theme }) => theme.colors.primary};
`;

const Sub = styled.p`
  margin: 0 0 28px;
  font-size: 15px;
  color: ${({ theme }) => theme.colors.secondary};
`;

const Grid = styled.div`
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: 16px;
`;

const Tile = styled.button`
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 14px;
  padding: 20px;
  text-align: left;
  background: ${({ theme }) => theme.colors.surface};
  border: 1px solid ${({ theme }) => theme.colors.border};
  border-radius: ${({ theme }) => theme.radii.md};
  box-shadow: ${({ theme }) => theme.shadows.card};
  color: ${({ theme }) => theme.colors.primary};
  transition: border-color 0.15s ease, box-shadow 0.15s ease, transform 0.15s ease;

  &:hover {
    border-color: ${({ theme }) => theme.colors.accentNeon};
    box-shadow: ${({ theme }) => theme.shadows.lift};
    transform: translateY(-1px);
  }

  &:hover .go {
    opacity: 1;
    transform: translate(2px, -2px);
  }
`;

const Row = styled.div`
  width: 100%;
  display: flex;
  align-items: center;
  justify-content: space-between;
`;

const IconBox = styled.span`
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 40px;
  height: 40px;
  border-radius: ${({ theme }) => theme.radii.sm};
  background: ${({ theme }) => theme.colors.accentSoft};
  color: ${({ theme }) => (theme.mode === 'dark' ? theme.colors.accentNeon : theme.colors.accent)};

  svg {
    font-size: 20px;
  }
`;

const Go = styled(FiArrowUpRight)`
  color: ${({ theme }) => theme.colors.muted};
  opacity: 0.6;
  transition: opacity 0.15s ease, transform 0.15s ease;
`;

const Name = styled.span`
  font-size: 16px;
  font-weight: 650;
`;

const Pages = styled.span`
  font-size: 13px;
  line-height: 1.5;
  color: ${({ theme }) => theme.colors.secondary};
`;

export const WelcomePage = () => {
  const { t } = useI18n();
  const user = useUser();
  const navigate = useNavigate();

  const sections = NAV_SECTIONS.map((section) => ({
    ...section,
    children: section.children.filter(({ key, resource = key }) => canViewFor(resource, user)),
  })).filter((section) => section.children.length > 0);

  return (
    <Wrap>
      <Kicker>{t('welcome.kicker')}</Kicker>
      <Title>{t('welcome.title')}</Title>
      <Sub>{t('welcome.sub')}</Sub>
      <Grid>
        {sections.map((section) => {
          const Icon = section.children[0].icon;
          return (
            <Tile key={section.key} type="button" onClick={() => navigate(section.children[0].path)}>
              <Row>
                <IconBox>
                  <Icon />
                </IconBox>
                <Go className="go" size={18} />
              </Row>
              <Name>{t(`nav.${section.key}`)}</Name>
              <Pages>{section.children.map((page) => t(`nav.${page.key}`)).join(', ')}</Pages>
            </Tile>
          );
        })}
      </Grid>
    </Wrap>
  );
};
