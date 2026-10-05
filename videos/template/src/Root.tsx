import { Composition } from "remotion";
import { LibasPremium, DURATION as PREMIUM_DURATION } from "./premium/LibasPremium";
import { FullFit, DURATION as FULLFIT_DURATION } from "./fullfit/FullFit";

// Each approved video is one composition. Start a new video by copying the
// closest folder (premium = search demo, fullfit = budget challenge) and
// registering it here.
export const Root: React.FC = () => (
  <>
    <Composition id="LibasPremium" component={LibasPremium} durationInFrames={PREMIUM_DURATION} fps={30} width={1080} height={1920} />
    <Composition id="FullFit" component={FullFit} durationInFrames={FULLFIT_DURATION} fps={30} width={1080} height={1920} />
  </>
);
