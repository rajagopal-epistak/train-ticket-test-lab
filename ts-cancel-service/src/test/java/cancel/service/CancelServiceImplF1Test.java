package cancel.service;

import edu.fudan.common.util.Response;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.mockito.junit.jupiter.MockitoSettings;
import org.mockito.quality.Strictness;
import org.mockito.verification.VerificationMode;
import org.springframework.http.HttpEntity;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpMethod;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.client.RestTemplate;

import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.contains;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.doReturn;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.timeout;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
class CancelServiceImplF1Test {

    private static final String DRAWBACK_URL =
            "http://ts-inside-payment-service/api/v1/inside_pay_service/inside_payment/drawback/user-1/50.0";

    @Mock
    private RestTemplate restTemplate;

    @Mock
    private FeatureFlagService featureFlagService;

    @InjectMocks
    private CancelServiceImpl cancelService;

    @BeforeEach
    void drawbackSucceeds() {
        doReturn(new ResponseEntity<>(new Response<>(1, "Draw Back Money Success", null), HttpStatus.OK))
                .when(restTemplate).exchange(contains("/drawback/"), eq(HttpMethod.GET), any(HttpEntity.class), eq(Response.class));
    }

    private void verifyDrawback(VerificationMode mode) {
        verify(restTemplate, mode).exchange(eq(DRAWBACK_URL), eq(HttpMethod.GET), any(HttpEntity.class), eq(Response.class));
    }

    @Test
    void flagOffRefundsBeforeReturning() {
        when(featureFlagService.isEnabled("tt-feat-01")).thenReturn(false);
        assertTrue(cancelService.refund("50.0", "user-1", new HttpHeaders()));
        verifyDrawback(times(1));
    }

    @Test
    void flagOnReturnsBeforeTheRefundThenRefundsLater() {
        when(featureFlagService.isEnabled("tt-feat-01")).thenReturn(true);
        cancelService.refundDelayMs = 500;
        assertTrue(cancelService.refund("50.0", "user-1", new HttpHeaders()));
        verifyDrawback(never());
        verifyDrawback(timeout(3000).times(1));
    }
}
