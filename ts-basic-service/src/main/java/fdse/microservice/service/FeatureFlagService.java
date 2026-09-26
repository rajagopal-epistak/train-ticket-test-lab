package fdse.microservice.service;

import dev.openfeature.sdk.Client;
import dev.openfeature.sdk.FlagEvaluationDetails;
import dev.openfeature.sdk.OpenFeatureAPI;
import org.springframework.stereotype.Service;

import javax.annotation.PostConstruct;

@Service
public class FeatureFlagService {

    private Client client;

    @PostConstruct
    public void initialize() {
        try {
            this.client = OpenFeatureAPI.getInstance().getClient("basic-service");
        } catch (Exception e) {
            // flags read as off
        }
    }

    public boolean isEnabled(String flagName) {
        try {
            if (client == null) {
                return false;
            }
            FlagEvaluationDetails<Boolean> details = client.getBooleanDetails(flagName, false);
            if ("ERROR".equals(details.getReason())) {
                return false;
            }
            return Boolean.TRUE.equals(details.getValue());
        } catch (Exception e) {
            return false;
        }
    }
}
