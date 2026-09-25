package fdse.microservice.service;

import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.mockito.junit.jupiter.MockitoSettings;
import org.mockito.quality.Strictness;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
class BasicServiceImplF14Test {

    @Mock
    private FeatureFlagService featureFlagService;

    @InjectMocks
    private BasicServiceImpl basicService;

    @Test
    void economyUsesConfiguredRateWhenFlagOff() {
        when(featureFlagService.isEnabled("tt-feat-14")).thenReturn(false);
        assertEquals(38.0, basicService.economyPrice(100, 0.38), 1e-9);
    }

    @Test
    void economyEqualsDistanceWhenFlagOn() {
        when(featureFlagService.isEnabled("tt-feat-14")).thenReturn(true);
        assertEquals(100.0, basicService.economyPrice(100, 0.38), 1e-9);
    }
}
