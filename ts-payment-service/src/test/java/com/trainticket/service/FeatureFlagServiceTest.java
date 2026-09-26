package com.trainticket.service;

import dev.openfeature.contrib.providers.flagd.FlagdProvider;
import dev.openfeature.sdk.OpenFeatureAPI;
import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertFalse;

class FeatureFlagServiceTest {

    @Test
    void readsOffBeforeInitialisation() {
        assertFalse(new FeatureFlagService().isEnabled("tt-feat-07"));
    }

    @Test
    void readsOffWhenFlagdIsUnreachable() {
        OpenFeatureAPI.getInstance().setProvider(new FlagdProvider("127.0.0.1", 1, false, null));
        FeatureFlagService service = new FeatureFlagService();
        service.initialize();
        assertFalse(service.isEnabled("tt-feat-07"));
    }
}
